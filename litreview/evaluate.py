# -*- coding: utf-8 -*-
"""金标准评估：标注样本 vs 筛选结果 → 逐判据与整体 Precision/Recall/F1。"""
from __future__ import annotations

import csv
import json

from .records import _norm_title


def _load_labels(path: str) -> dict[str, dict]:
    """labels CSV: 列含 doi 或 title，各判据列取值 1/0，overall 可选。"""
    labels = {}
    with open(path, "r", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            key = (row.get("doi") or "").strip().lower()
            if not key and row.get("title"):
                key = "t:" + _norm_title(row["title"])
            if not key:
                continue
            labels[key] = {k: (v or "").strip() for k, v in row.items()}
    return labels


def _match(trace: dict, labels: dict[str, dict]) -> dict | None:
    r = trace["record"]
    doi = (r.get("doi") or "").strip().lower()
    if doi and doi in labels:
        return labels[doi]
    return labels.get("t:" + _norm_title(r.get("title", "")))


def _prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f1


def evaluate(results_path: str, labels_path: str) -> dict:
    traces = []
    with open(results_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                traces.append(json.loads(line))
    labels = _load_labels(labels_path)

    crit_ids = sorted({c for t in traces for c in (t.get("criteria") or [])})
    counters = {cid: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for cid in crit_ids}
    counters["overall"] = {"tp": 0, "fp": 0, "fn": 0, "tn": 0}
    matched, unmatched = 0, 0

    for t in traces:
        lab = _match(t, labels)
        if lab is None:
            unmatched += 1
            continue
        matched += 1
        pred_all = t.get("final_answers") or {}
        pred_overall = t.get("final_overall")
        for cid in crit_ids:
            gold_s = lab.get(cid, "")
            if gold_s == "":
                continue
            gold = gold_s in ("1", "yes", "Yes", "Y", "true", "True")
            pred = pred_all.get(cid)
            if pred is None:
                counters[cid]["fn" if gold else "tn"] += 1
                continue
            k = ("tp" if gold else "fp") if pred else ("fn" if gold else "tn")
            counters[cid][k] += 1
        gold_overall = lab.get("overall", "")
        if gold_overall != "":
            gold = gold_overall in ("1", "yes", "Yes", "Y", "true", "True")
            if pred_overall is None:
                counters["overall"]["fn" if gold else "tn"] += 1
            else:
                k = ("tp" if gold else "fp") if pred_overall else ("fn" if gold else "tn")
                counters["overall"][k] += 1

    report = {"matched": matched, "unmatched": unmatched,
              "undetermined": sum(t.get("final_overall") is None for t in traces
                                  if _match(t, labels) is not None),
              "metrics": {}}
    for key, c in counters.items():
        p, r, f1 = _prf(c["tp"], c["fp"], c["fn"])
        report["metrics"][key] = {"precision": round(p, 4), "recall": round(r, 4),
                                  "f1": round(f1, 4), **c}
    return report


def format_report(report: dict) -> str:
    lines = [f"匹配样本: {report['matched']}（未匹配 {report['unmatched']}）", "",
             "| 判据 | Precision | Recall | F1 | TP | FP | FN | TN |",
             "|---|---|---|---|---|---|---|---|"]
    for key, m in report["metrics"].items():
        lines.append(f"| {key} | {m['precision']:.3f} | {m['recall']:.3f} | "
                     f"{m['f1']:.3f} | {m['tp']} | {m['fp']} | {m['fn']} | {m['tn']} |")
    return "\n".join(lines)
