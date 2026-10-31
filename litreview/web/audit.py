# -*- coding: utf-8 -*-
"""由任务结果生成一致、可阅读的审计统计与离线 HTML 报告。"""
from __future__ import annotations

import html
import json
from collections import Counter


def _different_answers(reviews: dict, criteria: list[str]) -> list[str]:
    outputs = list(reviews.values())
    return [cid for cid in criteria if len({(r or {}).get("answers", {}).get(cid) for r in outputs}) > 1]


def audit_summary(results: list[dict]) -> dict:
    criteria = sorted({cid for t in results for cid in t.get("criteria", [])})
    summary = {"total": len(results), "consistent": 0, "overall_disagreement": 0,
               "criterion_disagreement": 0, "arbitrated": 0, "arbitration_failed": 0,
               "review_failed": 0, "undetermined": 0, "include": 0, "exclude": 0}
    for trace in results:
        reviews = trace.get("reviews") or {}
        outputs = list(reviews.values())
        overalls = [(r or {}).get("overall") for r in outputs]
        criterion_diff = _different_answers(reviews, criteria)
        overall_diff = len(set(overalls)) > 1
        if overall_diff:
            summary["overall_disagreement"] += 1
        else:
            summary["consistent"] += 1
        if criterion_diff:
            summary["criterion_disagreement"] += 1
        path = trace.get("path", "")
        if path == "arbitrated":
            summary["arbitrated"] += 1
        if path == "arbitration_error":
            summary["arbitration_failed"] += 1
        if path == "review_error":
            summary["review_failed"] += 1
        if trace.get("final_overall") is None:
            summary["undetermined"] += 1
        elif trace.get("final_overall"):
            summary["include"] += 1
        else:
            summary["exclude"] += 1
    return summary


def audit_rows(results: list[dict], category: str = "", query: str = "") -> list[dict]:
    rows = []
    for trace in results:
        criteria = trace.get("criteria") or sorted({cid for r in trace.get("reviews", {}).values()
                                                   for cid in (r or {}).get("answers", {})})
        diff = _different_answers(trace.get("reviews") or {}, criteria)
        overall_diff = len({(r or {}).get("overall") for r in (trace.get("reviews") or {}).values()}) > 1
        if category == "overall" and not overall_diff:
            continue
        if category == "criteria" and not diff:
            continue
        if category == "arbitration_error" and trace.get("path") != "arbitration_error":
            continue
        if category == "review_error" and trace.get("path") != "review_error":
            continue
        text = (trace.get("record", {}).get("title", "") + trace.get("record", {}).get("doi", "")).lower()
        if query.lower() in text:
            rows.append({"record_id": trace["record_id"], "title": trace["record"].get("title", ""),
                         "doi": trace["record"].get("doi", ""), "path": trace.get("path"),
                         "different_criteria": diff, "overall_disagreement": overall_diff,
                         "final_overall": trace.get("final_overall"), "trace": trace})
    return rows


def error_groups(chunks: list[dict]) -> list[dict]:
    grouped = {}
    for chunk in chunks:
        if chunk["status"] == "done":
            continue
        key = (chunk["kind"], chunk["reviewer"], chunk.get("error") or "未完成")
        error = key[2]
        # 请求 ID 每次不同，不影响按同一根因聚合。
        error = __import__("re").sub(r" Request id: \S+", "", error)
        key = (key[0], key[1], error)
        item = grouped.setdefault(key, {"kind": key[0], "reviewer": key[1], "error": key[2],
                                        "count": 0, "chunk_indexes": []})
        item["count"] += 1
        item["chunk_indexes"].append(chunk["chunk_index"])
    return list(grouped.values())


def _decision(value):
    return {True: "纳入", False: "排除", None: "无法判定"}.get(value, "无法判定")


def _yn(value):
    return {True: "Yes", False: "No", None: "—"}.get(value, "—")


def render_html(task: dict, results: list[dict], chunks: list[dict]) -> str:
    summary = audit_summary(results)
    cfg = task["config"]
    criteria = cfg["criteria"]["criteria"]
    parts = []
    for trace in results:
        reviews = []
        for name, out in (trace.get("reviews") or {}).items():
            if not out:
                reviews.append(f"<section><h4>{html.escape(name)} · 无结果</h4></section>")
                continue
            answers = "".join(f"<tr><td>{html.escape(cid)}</td><td>{_yn(out.get('answers', {}).get(cid))}</td><td>{html.escape(out.get('reasonings', {}).get(cid, ''))}</td></tr>" for cid in trace.get("criteria", []))
            reviews.append(f"<section><h4>{html.escape(name)} · {_decision(out.get('overall'))}</h4><table><tr><th>判据</th><th>回答</th><th>理由</th></tr>{answers}</table></section>")
        arbitration = ""
        if trace.get("arbitration"):
            out = trace["arbitration"]
            arbitration = "<section><h4>仲裁</h4><table><tr><th>判据</th><th>回答</th><th>理由</th></tr>" + "".join(
                f"<tr><td>{html.escape(cid)}</td><td>{_yn(out.get('answers', {}).get(cid))}</td><td>{html.escape(out.get('reasonings', {}).get(cid, ''))}</td></tr>"
                for cid in trace.get("criteria", [])) + "</table></section>"
        r = trace["record"]
        parts.append(f"<article id='{html.escape(trace['record_id'])}'><h3>{html.escape(r.get('title', ''))}</h3><p class='meta'>{html.escape(trace['record_id'])} · {html.escape(r.get('doi', '无 DOI'))} · {html.escape(r.get('year', ''))}</p><p><b>最终：{_decision(trace.get('final_overall'))} · {html.escape(trace.get('path', ''))}</b></p><details><summary>标题与摘要</summary><p>{html.escape(r.get('abstract', '无摘要'))}</p></details><details><summary>检索到的知识</summary><pre>{html.escape(trace.get('knowledge_used', '无'))}</pre></details><div class='reviews'>{''.join(reviews)}</div>{arbitration}</article>")
    metrics = "".join(f"<div><b>{value}</b><span>{html.escape(label)}</span></div>" for label, value in [
        ("总文献", summary["total"]), ("整体一致", summary["consistent"]), ("整体分歧", summary["overall_disagreement"]),
        ("判据分歧", summary["criterion_disagreement"]), ("成功仲裁", summary["arbitrated"]), ("仲裁失败", summary["arbitration_failed"]),
        ("纳入", summary["include"]), ("排除", summary["exclude"]), ("无法判定", summary["undetermined"])])
    models = "".join(f"<li>{html.escape(r['name'])}：{html.escape(r.get('model', ''))}</li>" for r in cfg["reviewers"])
    if cfg.get("arbiter"):
        models += f"<li>仲裁：{html.escape(cfg['arbiter'].get('model', ''))} · temperature={html.escape(str(cfg['arbiter'].get('temperature', '默认')))}</li>"
    errors = "".join(f"<li>{html.escape(e['reviewer'])} · {e['count']} 个失败分块：{html.escape(e['error'])}</li>" for e in error_groups(chunks))
    return f"""<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'><title>{html.escape(task['name'])} · 审计报告</title><style>
body{{font:14px/1.75 -apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',sans-serif;max-width:1200px;margin:35px auto;padding:0 25px;color:#18352e}}h1{{font-size:28px}}h2{{margin-top:35px;border-bottom:2px solid #287158;padding-bottom:8px}}h3{{font-size:17px;line-height:1.5}}h4{{margin:0 0 8px}}.meta,small{{color:#6b7e73}}.metrics{{display:flex;flex-wrap:wrap;gap:12px}}.metrics div{{padding:12px 20px;border:1px solid #d4e0d6;min-width:80px}}.metrics b,.metrics span{{display:block}}.metrics b{{font-size:23px}}article{{border:1px solid #d4e0d6;border-radius:5px;padding:20px;margin:18px 0;break-inside:avoid}}.reviews{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}}section{{padding:12px;background:#f4f7f1}}table{{border-collapse:collapse;width:100%;font-size:12px}}td,th{{text-align:left;vertical-align:top;border-bottom:1px solid #dce4d7;padding:7px}}pre{{white-space:pre-wrap;font:12px/1.6 inherit}}details{{margin:10px 0}}@media print{{body{{margin:0;font-size:11px}}article{{break-inside:avoid}}details{{display:block}}}}
</style></head><body><h1>{html.escape(task['name'])} · 审计报告</h1><p class='meta'>任务 {html.escape(task['id'])} · 生成自本地任务数据。JSONL 是原始机器记录，本报告用于人工阅读。</p><div class='metrics'>{metrics}</div><h2>任务配置</h2><p>领域：{html.escape(cfg['criteria']['domain'])} · 判据组合：{html.escape(cfg['criteria'].get('logic', 'all'))} · 英文过滤：{html.escape(str(cfg.get('filters', {}).get('language', '未设置')))}</p><ul>{models}</ul><details><summary>完整判据与运行配置</summary><pre>{html.escape(json.dumps(cfg, ensure_ascii=False, indent=2))}</pre></details><h2>失败与异常</h2><ul>{errors or '<li>无失败分块</li>'}</ul><h2>逐篇审计</h2>{''.join(parts)}</body></html>"""
