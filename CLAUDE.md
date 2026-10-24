# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

Python 多智能体文献筛选框架（无 Web/前端，纯 CLI）。核心流程：题录收集 → 元数据预过滤 → 双评审（逐判据作答）→ 分歧仲裁（RRA）→ 全程留痕输出。方法论基于结构化判据（3T）+ 可选 RAG + 人工金标准回流。

## 常用命令

```bash
source .venv/bin/activate

# 冒烟测试（不调 LLM，走 MockAgent）——本项目没有单元测试，--mock 是主要验证手段
python -m litreview.cli screen --config config.yaml --mock --limit 5

# 真实筛选（先用 --limit 30~50 调判据，再全量）
python -m litreview.cli screen --config config.yaml --limit 50

# 只跑收集+过滤，不调 LLM，输出 filter_preview_*.csv
python -m litreview.cli screen --config config.yaml --filter-only

# 人工标注后评估（输入是 trace_*.jsonl，不是 results_*.csv）
python -m litreview.cli evaluate --results output/trace_xxx.jsonl --labels labels/sample_golden.csv

# 从模板创建新主题包
python -m litreview.cli new-theme themes/mytopic
```

依赖只有 `requirements.txt`（pyyaml/requests/openai/scikit-learn/pandas 等），`pip install -r requirements.txt`。API key 在 `.env` 中，由配置里各 agent 的 `api_key_env` 指定环境变量名。

## 架构

**主题包机制**（核心设计）：一个研究主题 = `themes/<name>/` 一个自包含目录（`criteria.yaml` 判据包 + `knowledge.md` + `config.yaml` + `labels_template.csv`），换领域零代码改动。根目录的 `criteria/` + `knowledge/`（稀土主题）是旧布局，仅作兼容。`themes/_template/` 是 `new-theme` 的脚手架来源。

**模块职责**（`litreview/`，约 1500 行）：

- `cli.py` — 三个子命令入口（screen / evaluate / new-theme），很薄，逻辑在 pipeline。
- `pipeline.py` — 核心。`collect_records`（多数据源收集+去重）→ `apply_filters`（确定性元数据过滤：语种/日期/文献类型）→ `Screener`（双评审并行 temperature=0 → 整体判定一致即采纳 → 分歧交仲裁；逐判据组合与整体判定不一致时以逐判据为准，记入 `overall_corrected`）。run_id 时间戳，四件套输出到 `output/`：`trace_*.jsonl`（全程留痕）、`results_*.csv`、`disputed_*.csv`（人工复核清单）、`stats_*.md`。
- `records.py` — `Record` 数据类；RIS / WoS 制表符 / CSV 自动识别加载；OpenAlex（cursor 翻页）与 Semantic Scholar 拉取；去重规则 DOI 优先、标题归一化兜底；OpenAlex 摘要 inverted index 重建。
- `criteria.py` — 判据包加载（`domain` 字段参数化 system prompt）；`combine` 实现逐判据答案的组合逻辑（`all` / `any`）。
- `prompts.py` — reviewer / arbiter 的 prompt 构建与输出解析。**双路径**：JSON 结构化输出（`response_format`）优先，端点不支持时回退文本模板 + 正则解析；trace 记录实际用的 `output_mode`。
- `llm.py` — `LLMClient`（任意 OpenAI 兼容端点）、`MockAgent`（`--mock` 时用，从 prompt 里的关键词造确定性答案）、`make_agent` 工厂。`structured: auto` 控制结构化输出尝试。
- `knowledge.py` — 可选 RAG：扫描主题目录 `*.md` 按 `## ` 分条，TF-IDF 字符级检索（离线、无 GPU）。目录缺省或无条目时跳过。
- `fewshot.py` — 金标准 CSV + trace 回流为 few-shot 参考案例（正负例均衡、确定性选取 k 个）。
- `evaluate.py` — 逐判据 P/R/F1；输入 trace jsonl + 标注 CSV，匹配用 DOI/标题归一化。

## 关键约定

- **运行时工作目录必须是仓库根目录**：主题包 config 里的相对路径（如 `themes/anammox/criteria.yaml`、`data/`）都相对 CWD 解析。
- 三种模式语义不同：`precision`（仅分歧件进人工清单）、`recall`（排除需评审一致或仲裁确认，"有评审 Yes 但整体排除"的边界件也进清单，适合系统性综述）、单评审（`reviewer_2: null`）配合 `--since` 做日常追踪。
- 解析失败自动重试一次，仍失败进人工清单，**不猜**。
- `require_abstract: true` 时缺摘要记录直接剔除。
- 所有运行产物进 `output/`，按 run_id 区分；不要把一次性实验产物提交进 git。
