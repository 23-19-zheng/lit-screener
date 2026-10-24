# -*- coding: utf-8 -*-
"""命令行入口。

用法:
  python -m litreview.cli screen    --config config.yaml [--mock] [--limit N] [--since YYYY-MM-DD]
                                   [--filter-only]   # 只跑收集+过滤，输出预览清单
  python -m litreview.cli evaluate  --results output/trace_xxx.jsonl --labels labels/sample.csv
  python -m litreview.cli new-theme themes/<name>    # 从模板创建新主题包
"""
from __future__ import annotations

import argparse
import os
import sys


def cmd_screen(args):
    from .pipeline import Screener, apply_filters, collect_records, load_config

    cfg = load_config(args.config)
    records = collect_records(cfg)
    print(f"加载题录 {len(records)} 篇（去重后）")

    filter_stats = {}
    dropped_pairs: list = []
    if cfg.get("filters"):
        records, dropped_pairs, filter_stats = apply_filters(records, cfg["filters"])
        if dropped_pairs:
            print(f"元数据过滤剔除 {len(dropped_pairs)} 篇: "
                  + "、".join(f"{k}×{v}" for k, v in filter_stats.items()))
        print(f"过滤后剩余 {len(records)} 篇")

    if args.filter_only:  # 预览：保留/剔除清单，不调 LLM
        import csv
        import datetime as _dt
        os.makedirs(args.out, exist_ok=True)
        prev = os.path.join(args.out, f"filter_preview_{_dt.datetime.now():%Y%m%d_%H%M%S}.csv")
        with open(prev, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["status", "reason", "id", "doi", "year", "date",
                        "language", "doctype", "title"])
            for r, reason in [(r, "") for r in records] + dropped_pairs:
                w.writerow(["剔除" if reason else "保留", reason, r.id, r.doi, r.year,
                            r.date, r.language, r.doctype, r.title[:200]])
        print(f"过滤预览已写出: {prev}（保留 {len(records)} / 剔除 {len(dropped_pairs)}）")
        return

    if args.since:
        records = [r for r in records if (r.year or "") >= args.since[:4]]
        print(f"--since {args.since}: 剩余 {len(records)} 篇")
    if args.limit:
        records = records[:args.limit]
        print(f"--limit {args.limit}: 剩余 {len(records)} 篇")
    if not records:
        print("没有可筛选的文献", file=sys.stderr)
        sys.exit(1)

    require_abs = cfg.get("run", {}).get("require_abstract", True)
    if require_abs:
        dropped = [r for r in records if not r.abstract.strip()]
        records = [r for r in records if r.abstract.strip()]
        if dropped:
            print(f"剔除缺摘要 {len(dropped)} 篇（require_abstract=true）")

    screener = Screener(cfg, mock=args.mock)
    screener.filter_stats = filter_stats
    summary = screener.run(records, out_dir=args.out)
    print("\n===== 汇总 =====")
    for k, v in summary["stats"].items():
        if k not in ("per_criterion_yes", "models"):
            print(f"  {k}: {v}")
    print(f"\n输出文件:\n  {summary['results_csv']}\n  {summary['disputed_csv']}\n  {summary['stats_md']}")


def cmd_new_theme(args):
    import shutil
    import yaml
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src = os.path.join(root, "themes", "_template")
    if not os.path.isdir(src):
        print(f"模板目录不存在: {src}", file=sys.stderr)
        sys.exit(1)
    if os.path.exists(args.dest):
        print(f"目标目录已存在: {args.dest}", file=sys.stderr)
        sys.exit(1)
    shutil.copytree(src, args.dest)
    # 判据就绪时生成对应列的 labels 模板
    crit_path = os.path.join(args.dest, "criteria.yaml")
    try:
        with open(crit_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        ids = [c["id"] for c in data.get("criteria") or [] if c.get("id")]
    except Exception:
        ids = []
    if ids:
        import csv
        lab = os.path.join(args.dest, "labels_template.csv")
        with open(lab, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["doi", "title"] + ids + ["overall"])
        print(f"主题包已创建: {args.dest}\n判据: {', '.join(ids)}\n标注模板: {lab}")
    else:
        print(f"主题包已创建: {args.dest}（criteria.yaml 尚无有效判据，编辑后可重跑本命令刷新标注模板）")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="litreview", description="文献智能筛选（判据+RAG+RRA）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_screen = sub.add_parser("screen", help="运行 RRA 筛选")
    p_screen.add_argument("--config", default="config.yaml")
    p_screen.add_argument("--mock", action="store_true", help="使用 Mock agent，不调用真实 LLM")
    p_screen.add_argument("--limit", type=int, default=0, help="只处理前 N 篇")
    p_screen.add_argument("--since", default="", help="只处理 YYYY-MM-DD 之后发表的文献")
    p_screen.add_argument("--filter-only", action="store_true",
                          help="只执行收集+过滤并输出预览清单，不调用 LLM")
    p_screen.add_argument("--out", default="output", help="输出目录")

    p_ev = sub.add_parser("evaluate", help="金标准评估 P/R/F1")
    p_ev.add_argument("--results", required=True, help="trace_*.jsonl 路径")
    p_ev.add_argument("--labels", required=True, help="人工标注 CSV 路径")

    p_new = sub.add_parser("new-theme", help="从 themes/_template 创建新主题包目录")
    p_new.add_argument("dest", help="目标目录，如 themes/mytopic")

    args = parser.parse_args(argv)

    # 加载 .env（存在才加载）
    try:
        from dotenv import load_dotenv
        base = os.path.dirname(os.path.abspath(args.config)) if args.cmd == "screen" else os.getcwd()
        load_dotenv(os.path.join(base, ".env") if args.cmd == "screen" else ".env")
    except ImportError:
        pass

    if args.cmd == "screen":
        cmd_screen(args)
    elif args.cmd == "evaluate":
        from .evaluate import evaluate, format_report
        report = evaluate(args.results, args.labels)
        print(format_report(report))
    elif args.cmd == "new-theme":
        cmd_new_theme(args)


if __name__ == "__main__":
    main()
