# -*- coding: utf-8 -*-
"""RRA 筛选管线：双评审 → 一致采纳 / 分歧仲裁，全程留痕。"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

from .criteria import combine, load_pack
from .fewshot import build_bank, render_examples
from .knowledge import KnowledgeRetriever, load_entries
from .llm import make_agent
from .prompts import (SYSTEM_ARBITER, build_arbiter_prompt, build_reviewer_prompt,
                      parse_arbiter_output, parse_json_arbiter, parse_json_review,
                      parse_review_output, system_reviewer)
from .records import Record, dedupe, load_records, norm_language

_print_lock = threading.Lock()


def _log(msg: str):
    with _print_lock:
        print(msg, flush=True)


def load_config(path: str) -> dict:
    import yaml
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def collect_records(cfg: dict) -> list[Record]:
    """按配置的 data.inputs 拉取/加载题录并去重。全局 filters 的日期区间下推给 OpenAlex。"""
    records: list[Record] = []
    gfilters = cfg.get("filters") or {}
    for spec in cfg["data"]["inputs"]:
        typ = spec["type"]
        if typ == "file":
            records.extend(load_records(spec["path"]))
        elif typ == "openalex":
            from .records import fetch_openalex
            records.extend(fetch_openalex(
                spec["query"], from_year=spec.get("from_year"),
                max_records=spec.get("max_records", 500),
                mailto=spec.get("mailto", ""),
                date_from=spec.get("date_from", gfilters.get("date_from", "")),
                date_to=spec.get("date_to", gfilters.get("date_to", "")),
                api_key=os.environ.get(spec.get("api_key_env", ""),
                                       spec.get("api_key", ""))))
        elif typ == "semantic_scholar":
            from .records import fetch_semantic_scholar
            records.extend(fetch_semantic_scholar(
                spec["query"], from_year=spec.get("from_year"),
                max_records=spec.get("max_records", 500),
                api_key_env=spec.get("api_key_env", "S2_API_KEY")))
        else:
            raise ValueError(f"未知数据源类型: {typ}")
    return dedupe(records)


# ---------------------------------------------------------------- 元数据预过滤

def _norm_bound(v: str, is_to: bool) -> str:
    """过滤边界归一化为可字符串比较的 ISO 日期：'2000' → 2000-01-01 / 2000-12-31。"""
    v = str(v or "").strip()
    if len(v) == 4 and v.isdigit():
        return f"{v}-12-31" if is_to else f"{v}-01-01"
    return v


def _date_bounds(r: Record) -> tuple[str | None, str | None]:
    """记录日期的 [下界, 上界]（字符串可比较）。仅知年份时按全年计；完全未知返回 (None, None)。"""
    d = (r.date or "").strip()
    if len(d) >= 7:
        return f"{d[:7]}-01", f"{d[:7]}-31"
    y = (r.year or "").strip()
    if len(y) == 4 and y.isdigit():
        return f"{y}-01-01", f"{y}-12-31"
    if d:
        return d, d
    return None, None


def apply_filters(records: list[Record], filters: dict) -> tuple[list[Record], list[tuple[Record, str]], dict]:
    """确定性元数据过滤。元数据未知的记录保留（交 LLM 判据兜底）。

    返回 (保留列表, [(被剔记录, 原因)], 剔除统计)。
    """
    stats: dict[str, int] = {}
    lang_want = norm_language(filters.get("language", "") or "")
    date_from = _norm_bound(filters.get("date_from", ""), is_to=False)
    date_to = _norm_bound(filters.get("date_to", ""), is_to=True)
    inc = [s.lower() for s in filters.get("doctype_include") or []]
    exc = [s.lower() for s in filters.get("doctype_exclude") or []]

    def _drop(r: Record, reason: str):
        stats[reason] = stats.get(reason, 0) + 1
        dropped.append((r, reason))

    kept: list[Record] = []
    dropped: list[tuple[Record, str]] = []
    for r in records:
        if lang_want and r.language and r.language != lang_want:
            _drop(r, f"语种={r.language}")
            continue
        if date_from or date_to:
            lo, hi = _date_bounds(r)
            if hi and date_from and hi < date_from:
                _drop(r, f"早于{date_from}")
                continue
            if lo and date_to and lo > date_to:
                _drop(r, f"晚于{date_to}")
                continue
        dt = (r.doctype or "").strip().lower()
        if dt:
            if inc and not any(s in dt for s in inc):
                _drop(r, f"类型={r.doctype}")
                continue
            if any(s in dt for s in exc):
                _drop(r, f"类型={r.doctype}")
                continue
        kept.append(r)
    return kept, dropped, stats


class Screener:
    def __init__(self, cfg: dict, mock: bool = False):
        self.cfg = cfg
        self.mode = cfg.get("run", {}).get("mode", "precision")
        self.logic = cfg.get("criteria", {}).get("inclusion_logic", "all")
        self.pack, self.criteria = load_pack(
            cfg["criteria"]["pack"], cfg["criteria"].get("active"))
        self.system_reviewer = system_reviewer(self.pack.domain)
        self.filter_stats: dict[str, int] = {}

        if mock:
            cfg = dict(cfg)
            cfg["agents"] = {r: (dict(s, provider="mock", role=r) if s else None)
                             for r, s in cfg["agents"].items()}
            self.cfg = cfg

        self.agent_a = make_agent(cfg["agents"]["reviewer_1"])
        spec_b = cfg["agents"].get("reviewer_2")
        self.agent_b = make_agent(spec_b) if spec_b else None
        self.agent_arb = make_agent(cfg["agents"]["arbiter"])

        # 知识库可选：未配置或目录无条目时跳过 RAG
        kcfg = cfg.get("knowledge") or {}
        entries = load_entries(kcfg["dir"]) if kcfg.get("dir") else []
        self.retriever = (KnowledgeRetriever(entries, kcfg.get("top_k", 4))
                          if entries else None)

        # 金标准 few-shot：人工标注累积后重跑自动生效
        fcfg = cfg.get("fewshot") or {}
        self.fewshot_text = ""
        if fcfg.get("labels"):
            bank = build_bank(fcfg["labels"], [c.id for c in self.criteria],
                              fcfg.get("traces"))
            self.fewshot_text = render_examples(bank, fcfg.get("k", 2))
            if self.fewshot_text:
                _log(f"few-shot: 注入 {fcfg.get('k', 2)} 个人工裁定示例")

    # ------------------------------------------------------------------ 单篇

    @staticmethod
    def _json_ready(agent) -> bool:
        return getattr(agent, "structured", "text") == "auto" and hasattr(agent, "complete_json")

    def _review(self, agent, record: Record, knowledge_text: str) -> dict:
        ids = [c.id for c in self.criteria]
        if self._json_ready(agent):  # 优先结构化输出，失败回退文本
            jp = build_reviewer_prompt(self.pack, self.criteria, record, knowledge_text,
                                       self.fewshot_text, output_mode="json")
            try:
                out = parse_json_review(agent.complete_json(self.system_reviewer, jp), ids)
                if out is not None and not (out["overall"] is None and
                                            all(v is None for v in out["answers"].values())):
                    out["output_mode"] = "json"
                    return out
            except Exception:
                pass
        prompt = build_reviewer_prompt(self.pack, self.criteria, record,
                                       knowledge_text, self.fewshot_text)
        text = agent.complete(self.system_reviewer, prompt)
        out = parse_review_output(text, ids)
        out["output_mode"] = "text"
        if out["overall"] is None or all(v is None for v in out["answers"].values()):
            # 格式容错：重试一次，附严格格式指令
            retry = prompt + ("\n\n注意：你上一次的输出不符合格式要求。"
                              "请严格按如下格式重新输出全部字段，不要添加任何其他内容：\n"
                              + f"Response {', '.join(ids)}: Yes/No\n"
                              + f"Reasoning ...\nOverall Response: Yes/No\nReasoning: ...")
            text = agent.complete(self.system_reviewer, retry)
            out2 = parse_review_output(text, ids)
            out2["retried"] = True
            out2["output_mode"] = "text"
            return out2
        return out

    def _arbitrate(self, record: Record, out_a: dict, out_b: dict, knowledge_text: str) -> dict:
        ids = [c.id for c in self.criteria]
        if self._json_ready(self.agent_arb):
            jp = build_arbiter_prompt(self.pack, self.criteria, record, out_a, out_b,
                                      knowledge_text, output_mode="json")
            try:
                arb = parse_json_arbiter(
                    self.agent_arb.complete_json(SYSTEM_ARBITER, jp), ids)
                if arb is not None and arb["overall"] is not None:
                    arb["output_mode"] = "json"
                    return arb
            except Exception:
                pass
        ap = build_arbiter_prompt(self.pack, self.criteria, record, out_a, out_b,
                                  knowledge_text)
        arb_text = self.agent_arb.complete(SYSTEM_ARBITER, ap)
        arb = parse_arbiter_output(arb_text, ids)
        arb["output_mode"] = "text"
        return arb

    def screen_one(self, record: Record) -> dict:
        if self.retriever:
            kb_entries = self.retriever.retrieve(
                f"{record.title}\n{record.abstract[:1500]}")
            knowledge_text = self.retriever.format_for_prompt(kb_entries)
        else:
            kb_entries, knowledge_text = [], ""
        trace = {
            "record": record.to_dict(),
            "criteria": [c.id for c in self.criteria],
            "knowledge_used": [e.title for e in kb_entries],
        }

        out_a = self._review(self.agent_a, record, knowledge_text)
        trace["reviewer_a"] = out_a
        if self.agent_b is None:  # 追踪模式：单评审
            final_answers, final_overall = out_a["answers"], out_a["overall"]
            trace["path"] = "single_reviewer"
        else:
            out_b = self._review(self.agent_b, record, knowledge_text)
            trace["reviewer_b"] = out_b
            if out_a["overall"] is not None and out_a["overall"] == out_b["overall"]:
                trace["path"] = "consistent"
                final_answers, final_overall = out_a["answers"], out_a["overall"]
            else:
                trace["path"] = "disputed"
                arb = self._arbitrate(record, out_a, out_b, knowledge_text)
                trace["arbitration"] = arb
                if arb["overall"] is None:
                    trace["path"] = "arbitration_parse_error"
                    final_answers, final_overall = None, None
                else:
                    trace["path"] = "arbitrated"
                    final_answers, final_overall = arb["answers"], arb["overall"]

        # 解析失败的兜底
        if final_overall is None or final_answers is None or any(
                v is None for v in final_answers.values()):
            trace["path"] = trace.get("path", "") + "+parse_error" if trace.get("path") else "parse_error"
            final_overall = None

        # 组合校验：整体判定应与逐判据组合一致（不一致时以逐判据组合为准）
        if final_overall is not None:
            composed = combine(final_answers, self.logic)
            if composed is not None and composed != final_overall:
                trace["overall_corrected"] = (final_overall, composed)
                final_overall = composed

        include = final_overall  # True=纳入 False=排除 None=无法判定
        human_review, reason = False, ""
        if include is None:
            human_review, reason = True, "解析失败/无法判定"
        elif self.mode == "precision":
            if trace["path"].startswith(("disputed", "arbitration_parse_error")):
                human_review, reason = True, "评审分歧"
        elif self.mode == "recall":
            if trace["path"].startswith(("disputed", "arbitration_parse_error")):
                human_review, reason = True, "评审分歧"
            elif include is False:
                yes_by_any = any(
                    (trace.get("reviewer_a", {}).get("answers") or {}).get(c.id) is True
                    or (trace.get("reviewer_b", {}).get("answers") or {}).get(c.id) is True
                    for c in self.criteria)
                if yes_by_any:
                    human_review, reason = True, "边界案例：有评审判 Yes 但整体被排除"

        trace["final_overall"] = include
        trace["final_answers"] = final_answers
        trace["human_review"] = human_review
        trace["review_reason"] = reason
        return trace

    # ------------------------------------------------------------------ 批量

    def run(self, records: list[Record], out_dir: str = "output") -> dict:
        run_id = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        os.makedirs(out_dir, exist_ok=True)
        trace_path = os.path.join(out_dir, f"trace_{run_id}.jsonl")
        traces: list[dict] = []
        done = 0

        def _work(r: Record) -> dict:
            nonlocal done
            try:
                t = self.screen_one(r)
            except Exception as e:
                t = {"record": r.to_dict(), "path": "error", "error": str(e),
                     "final_overall": None, "human_review": True,
                     "review_reason": f"运行异常: {e}",
                     "criteria": [c.id for c in self.criteria],
                     "final_answers": {}}
            with _print_lock:
                done += 1
                if done % 10 == 0 or done == len(records):
                    print(f"进度: {done}/{len(records)}", flush=True)
            return t

        with ThreadPoolExecutor(max_workers=self.cfg.get("run", {}).get("threads", 10)) as ex:
            traces = list(ex.map(_work, records))

        with open(trace_path, "w", encoding="utf-8") as f:
            for t in traces:
                f.write(json.dumps(t, ensure_ascii=False) + "\n")

        summary = self._write_reports(traces, run_id, out_dir)
        _log(f"完成。trace: {trace_path}")
        return summary

    def _write_reports(self, traces: list[dict], run_id: str, out_dir: str) -> dict:
        ids = [c.id for c in self.criteria]
        # results.csv
        res_path = os.path.join(out_dir, f"results_{run_id}.csv")
        with open(res_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "doi", "year", "title", "decision", "human_review",
                        "review_reason", "path"] + ids)
            for t in traces:
                r = t["record"]
                dec = {True: "include", False: "exclude", None: "undetermined"}[
                    t.get("final_overall")]
                fa = t.get("final_answers") or {}
                w.writerow([r["id"], r["doi"], r["year"], r["title"][:200], dec,
                            "Y" if t.get("human_review") else "", t.get("review_reason", ""),
                            t.get("path", "")] + [fa.get(i, "") for i in ids])
        # disputed.csv
        dis_path = os.path.join(out_dir, f"disputed_{run_id}.csv")
        disputed = [t for t in traces if t.get("human_review")]
        with open(dis_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["id", "doi", "title", "reason", "path"] + ids)
            for t in disputed:
                r = t["record"]
                fa = t.get("final_answers") or {}
                w.writerow([r["id"], r["doi"], r["title"][:200], t.get("review_reason", ""),
                            t.get("path", "")] + [fa.get(i, "") for i in ids])
        # stats.md
        n = len(traces)
        n_inc = sum(1 for t in traces if t.get("final_overall") is True)
        n_exc = sum(1 for t in traces if t.get("final_overall") is False)
        n_und = n - n_inc - n_exc
        paths = [t.get("path", "") for t in traces]
        stats = {
            "total": n, "include": n_inc, "exclude": n_exc, "undetermined": n_und,
            "human_review": len(disputed),
            "disputed_overall": sum(1 for p in paths if p == "disputed"),
            "arbitrated": sum(1 for p in paths if p == "arbitrated"),
            "consistent": sum(1 for p in paths if p == "consistent"),
            "single_reviewer": sum(1 for p in paths if p == "single_reviewer"),
            "parse_error_or_error": sum(1 for p in paths
                                        if "parse_error" in p or p == "error"),
            "per_criterion_yes": {i: sum(1 for t in traces
                                         if (t.get("final_answers") or {}).get(i) is True)
                                  for i in ids},
            "mode": self.mode, "logic": self.logic,
            "json_reviews": sum(1 for t in traces for rk in ("reviewer_a", "reviewer_b")
                                if (t.get(rk) or {}).get("output_mode") == "json"),
            "models": {"reviewer_1": getattr(self.agent_a, "model", "?"),
                       "reviewer_2": getattr(self.agent_b, "model", "无（单评审）"),
                       "arbiter": getattr(self.agent_arb, "model", "?")},
        }
        md_path = os.path.join(out_dir, f"stats_{run_id}.md")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(f"# 筛选统计 ({run_id})\n\n")
            f.write(f"- 模式: {self.mode} | 组合逻辑: {self.logic}\n")
            f.write(f"- 模型: R1={stats['models']['reviewer_1']}, "
                    f"R2={stats['models']['reviewer_2']}, "
                    f"仲裁={stats['models']['arbiter']}\n")
            f.write(f"- 领域: {self.pack.domain} | 知识库: "
                    f"{'开' if self.retriever else '关'} | few-shot: "
                    f"{'开' if self.fewshot_text else '关'} | "
                    f"结构化输出调用: {stats['json_reviews']}\n")
            if self.filter_stats:
                f.write("- 预过滤剔除: " + "、".join(
                    f"{k}×{v}" for k, v in self.filter_stats.items()) + "\n")
            f.write(f"| 指标 | 数值 |\n|---|---|\n")
            for k in ["total", "include", "exclude", "undetermined", "human_review",
                      "consistent", "disputed_overall", "arbitrated",
                      "single_reviewer", "parse_error_or_error"]:
                f.write(f"| {k} | {stats[k]} |\n")
            f.write("\n## 逐判据最终 Yes 数\n\n")
            for i in ids:
                f.write(f"- {i} ({self.pack.get(i).name}): "
                        f"{stats['per_criterion_yes'][i]}/{n}\n")
        return {"run_id": run_id, "stats": stats,
                "results_csv": res_path, "disputed_csv": dis_path,
                "stats_md": md_path}
