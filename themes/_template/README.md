# 新主题包调优工作流

1. **验证检索与过滤**（不花 LLM 费用）：
   ```bash
   python -m litreview.cli screen --config themes/<主题>/config.yaml --filter-only
   ```
   核对 `output/filter_preview_*.csv`：剔除的该剔吗？保留的检索式命中理想吗？

2. **小样本试跑**：
   ```bash
   python -m litreview.cli screen --config themes/<主题>/config.yaml --limit 30
   ```
   人工核对 `results_*.csv`：exclude 中有漏 → 改对应判据的 guidance（写清边界）；
   include 中有混 → 增加排除项。

3. **金标准 + 评估 + few-shot 闭环**：
   - 用 `labels_template.csv` 人工标注 30~100 篇（doi/title + 各判据 1/0 + overall）；
   - `python -m litreview.cli evaluate --results output/trace_xxx.jsonl --labels labels/xxx.csv`
     看逐判据 P/R/F1，最弱判据改 guidance；
   - config 加 `fewshot` 段后重跑，人工裁定自动注入为参考案例。

4. **达标后全量运行**（去掉 `--limit`）。

判据 guidance 的"纳入/排除/边界"写得越明确，筛选越准——这是整个方法精度的首要来源，
RAG 知识库只是增量。
