# -*- coding: utf-8 -*-
"""金标准 few-shot 示例库：人工标注 + 历史题录 → 评审 prompt 参考案例。

labels CSV 与 evaluate 同格式（doi/title + 各判据 1/0 + overall）。
摘要文本从历史 trace_*.jsonl 中按 DOI/标题匹配补全；匹配不到时仅用标题。
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass

from .records import _norm_title


@dataclass
class FewShotExample:
    title: str
    abstract: str
    labels: dict[str, bool]      # 判据 id → 人工答案
    overall: bool

    @property
    def stable_key(self) -> str:
        return _norm_title(self.title) or self.title


def _is_yes(v) -> bool:
    return str(v or "").strip().lower() in ("1", "yes", "y", "true")


def build_bank(labels_path: str, criteria_ids: list[str],
               trace_paths: list[str] | None = None) -> list[FewShotExample]:
    """从 labels（+可选 trace 补摘要）构建示例库。"""
    texts: dict[str, str] = {}  # key → "title\nabstract"
    for tp in trace_paths or []:
        try:
            with open(tp, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    r = (json.loads(line).get("record") or {})
                    doi = (r.get("doi") or "").strip().lower()
                    key = doi if doi else "t:" + _norm_title(r.get("title", ""))
                    if key:
                        texts[key] = f"{r.get('title', '')}\n{r.get('abstract', '')}"
        except OSError:
            continue

    examples: list[FewShotExample] = []
    with open(labels_path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            doi = (row.get("doi") or "").strip().lower()
            key = doi if doi else "t:" + _norm_title(row.get("title", ""))
            if not key:
                continue
            text = texts.get(key, row.get("title", "") or "")
            title, _, abstract = text.partition("\n")
            labels = {cid: _is_yes(row.get(cid))
                      for cid in criteria_ids if (row.get(cid) or "").strip() != ""}
            if not labels:
                continue
            overall_raw = (row.get("overall") or "").strip()
            overall = _is_yes(overall_raw) if overall_raw else all(labels.values())
            examples.append(FewShotExample(title=title.strip(), abstract=(abstract or "").strip(),
                                           labels=labels, overall=overall))
    return examples


def render_examples(examples: list[FewShotExample], k: int = 2) -> str:
    """确定性选取 k 个示例（正负例均衡），渲染为 prompt 参考案例段。"""
    if not examples or k <= 0:
        return ""
    pos = sorted([e for e in examples if e.overall], key=lambda e: e.stable_key)
    neg = sorted([e for e in examples if not e.overall], key=lambda e: e.stable_key)
    picked: list[FewShotExample] = []
    for pool in (pos, neg):  # 先各取一半，不足的由另一个池补齐
        picked.extend(pool[: k // 2])
    for pool in (pos, neg):
        need = k - len(picked)
        if need > 0:
            picked.extend(pool[k // 2: k // 2 + need])
    blocks = []
    for e in picked:
        ans = " ".join(f"{cid}={'Yes' if v else 'No'}" for cid, v in e.labels.items())
        abs_ = e.abstract[:400] + "…" if len(e.abstract) > 400 else e.abstract
        blocks.append(f"- Title: {e.title}\n  Abstract: {abs_ or '（无）'}\n"
                      f"  人工裁定: {ans} | Overall: {'Yes' if e.overall else 'No'}")
    return "\n".join(blocks)
