# lit-screener — 主题包化多智能体文献筛选框架

面向科研文献的 AI 辅助筛选系统（首个应用领域：稀土研究；当前交付：厌氧氨氧化
脱氮废水处理），方法论借鉴 Wang et al., *A domain-enhanced multi-agent framework
for trustworthy literature screening in water research*, Water Research 308 (2027)
126813，并在主题包、元数据过滤、结构化输出、few-shot 反馈上做了扩展。

## 快速支持一个新主题（主题包机制）

一个研究主题 = `themes/<name>/` 一个自包含目录（判据包 + 知识库 + 运行配置 +
标注模板），**换/加领域零代码改动**：

```bash
python -m litreview.cli new-theme themes/mytopic   # 从模板脚手架生成
# 1) 编辑 themes/mytopic/criteria.yaml（guidance 写清"纳入/排除/边界"三段）
# 2) --filter-only 预览检索式与过滤命中，调 query/filters
# 3) --limit 30 试跑 → 核对 results.csv → 调 guidance → 标注金标准 → evaluate
```

现成主题包：

| 主题 | 目录 | 说明 |
|---|---|---|
| 厌氧氨氧化脱氮 | `themes/anammox/` | 5 判据（A1 核心/A2 脱氮/A3 废水/A4 类型/A5 语种），all 组合；en；2000-01-01~2026-09-30 |
| 稀土回收 | `criteria/` + `knowledge/`（旧布局） | 3T 判据包 |

## 方法论对照

| 组件 | 原论文 | 本框架 |
|---|---|---|
| 结构化判据 | 固定 3T（Target-Technology-Type） | 主题包 YAML 判据包，条数不限，按需选子集 + 组合逻辑（all/any） |
| 域知识 RAG | ~50 条人工条目 + 句向量检索 | Markdown 知识条目 + TF-IDF 字符级检索（无 GPU、离线、**可选**） |
| 多智能体 | 5 家 LLM 双评审 + 仲裁（RRA） | 任意 OpenAI 兼容/Anthropic 模型任意指派 R1/R2/仲裁 |
| 输出协议 | 固定文本模板 + 人工解析 | JSON 结构化输出优先（response_format），文本模板兜底 |
| 领域身份 | 固定 prompt | 判据包 `domain` 字段参数化 system prompt |
| 元数据过滤 | WoS 导出 + 人工清洗 | `filters` 确定性预过滤（语种/日期区间/文献类型），未知件交 LLM 兜底 |
| 人工复核 | 只看分歧件 | 分歧件 + 边界件（recall 模式）+ 解析失败件 |
| 评估 | 9 人标注金标准，P/R/F1 | `evaluate` 子命令逐判据 P/R/F1；金标准可回流为 few-shot 参考案例 |

核心思想（原论文消融实验结论）：
- **结构化判据是精度的主要来源**（简单 prompt F1 0.753 → 3T 0.849），逐判据作答使错误可归因到具体标准；
- **RAG 只在结构化判据之上起增量作用**（3T+RAG 0.878），单独用反而引入噪声；
- **双评审分歧是可追溯错误信号**，人工只需重点复核分歧件与抽检一致件。

## 快速开始

```bash
cd /Users/zc/AIWorkspace/lit-screener
source .venv/bin/activate

# 1) 配置：复制 config.example.yaml → config.yaml，修改数据源/判据/模型
# 2) 冒烟（不调 LLM）
python -m litreview.cli screen --config config.yaml --mock --limit 5

# 3) 真实筛选
python -m litreview.cli screen --config config.yaml            # 全量
python -m litreview.cli screen --config config.yaml --limit 50 # 先跑 50 篇调判据

# 4) 人工标注小样本后评估
python -m litreview.cli evaluate --results output/trace_xxx.jsonl --labels labels/sample_golden.csv
```

API key 在 `.env` 中配置（模板见 `.env.example`），由 `api_key_env` 指定环境变量名。

## 配置说明（以 themes/anammox/config.yaml 为例）

### 判据包（主题包核心）

```yaml
criteria:
  pack: themes/anammox/criteria.yaml
  active: [A1, A2, A3, A4, A5]   # 本次启用的判据子集
  inclusion_logic: all           # all=全部满足才纳入 | any=任一满足即纳入
```

判据包含 `domain` 字段（评审 system prompt 的领域身份）与若干判据
（`id/name/question/guidance`）。**guidance 的"纳入/排除/边界"写得越明确，
筛选越准**（原论文精度关键来源）。模板见 `themes/_template/criteria.yaml`。

### 元数据预过滤（确定性，不花 LLM 调用）

```yaml
filters:
  language: en                 # 语种归一化后精确匹配；未知语种保留交判据兜底
  date_from: "2000-01-01"      # OpenAlex 时自动下推 API；本地对 year 宽松判定
  date_to: "2026-09-30"
  doctype_include: []          # 空=不设白名单
  doctype_exclude: [review, editorial, letter, meeting abstract, book chapter, ...]
```

`--filter-only` 可只跑收集+过滤，输出保留/剔除预览清单（不调 LLM）。

### 数据源

```yaml
data:
  inputs:
    - type: file                 # RIS / WoS 制表符导出 / CSV 自动识别
      path: data/savedrecs.txt
    - type: openalex             # filters 日期区间自动下推；cursor 翻页(>200条)需免费 key
      query: "anaerobic ammonium oxidation"
      max_records: 500
      api_key_env: OPENALEX_API_KEY
    - type: semantic_scholar     # 无 key 限速（100次/5分钟）
      query: "anammox nitrogen removal"
```

去重规则：DOI 优先，标题归一化兜底。`run.require_abstract: true` 时剔除缺摘要记录。

### 模式（对应三种用途）

| 模式 | 用途 | 行为 |
|---|---|---|
| `precision` | 构建结构化数据集 | 判据组合判定；仅分歧件进人工清单 |
| `recall` | 系统性综述（漏检代价高） | 排除需经评审一致或仲裁确认；"有评审判 Yes 但整体被排除"的边界件也进人工清单 |
| 追踪 | 日常文献追踪 | `agents.reviewer_2: null` 退化为单评审轻量运行；配合 `--since 2025-01-01` 只筛新文献 |

### Agent 指派与输出协议

```yaml
agents:
  reviewer_1: {provider: openai_compatible, model: deepseek-v4.1-flash,
               base_url: https://ark.cn-beijing.volces.com/api/coding/v3,
               api_key_env: ARK_API_KEY, structured: auto}
  reviewer_2: {provider: openai_compatible, model: glm-5.3-flash, ...}
  arbiter:    {provider: openai_compatible, model: glm-5.3-flashx, ...}
```

`structured: auto`（默认）优先走 `response_format` JSON 结构化输出（消灭解析失败），
端点不支持时自动回退文本模板 + 正则解析；trace 记录实际使用的 `output_mode`。

RRA 流程：双评审并行（temperature=0）→ 整体判定一致即采纳 → 分歧交仲裁（对比双方
推理链裁定）。逐判据组合与整体判定不一致时以逐判据组合为准（记录在
`overall_corrected`）。解析失败自动重试一次，仍失败进人工清单，不猜。

### 金标准 few-shot 反馈（可选）

```yaml
fewshot:
  labels: labels/anammox_golden.csv   # 与 evaluate 同格式
  traces: [output/trace_xxx.jsonl]    # 可选：补全示例摘要
  k: 2                                 # 注入的参考案例数（正负例均衡、确定性选取）
```

人工标注累积后重跑自动生效，与 `evaluate` 形成闭环：评估定位最弱判据 →
改 guidance → 标注件回流为 few-shot 参考案例。

### 知识库（可选）

`knowledge.dir` 指向主题目录（扫 `*.md` 按 `## ` 分条）；目录缺省或无条目时
跳过 RAG，适合轻量主题。

## 输出说明

每次运行在 `output/` 生成四件套（按 run_id 时间戳区分；`--filter-only` 时仅输出
`filter_preview_*.csv`）：

| 文件 | 内容 |
|---|---|
| `trace_*.jsonl` | 全程留痕：双方逐判据答案与理由、RAG 知识条目、仲裁记录、输出模式、最终判定 |
| `results_*.csv` | 每篇最终决定 + 逐判据 Yes/No + 路径 + 人工复核标记 |
| `disputed_*.csv` | 人工复核清单（分歧/边界/解析失败件） |
| `stats_*.md` | 汇总统计 + 逐判据通过率 + 预过滤剔除统计（定位最弱判据，针对性修 guidance） |

## 调优工作流（建议）

1. 先用 `--limit 30~50` 跑真实数据；
2. 人工快速核对 results.csv，重点看 exclude 中是否有漏（调 guidance）、include 中是否有混（加排除项）；
3. 人工标注 50~100 篇金标准（`labels/sample_golden.csv` 格式：doi/title + 各判据 1/0 + overall）；
4. `evaluate` 看逐判据 F1，最弱判据改 guidance 后重跑；
5. 达标后再全量运行。

## 已验证

- Mock 端到端：一致直采 / 分歧仲裁 / 解析失败兜底三条路径均验证通过
- 元数据过滤：语种/日期区间/文献类型预过滤 + `--filter-only` 预览清单验证通过
- 真实 API（火山方舟，deepseek-v4.1-flash + glm-5.3-flash + glm-5.3-flashx）：
  JSON 结构化输出路径验证通过
- OpenAlex 真实拉取：摘要重建、去重、日期区间下推正常
- 评估模块：P/R/F1 计算手工核对无误

## 已知限制

- 双评审为模型族级多样性（同一方舟端点的异构模型），非跨厂商独立失效；
- 仅基于标题+摘要筛选（原论文同），全文级判断需人工复核环节；
- 元数据过滤依赖数据源提供语种/类型/日期字段，缺失件保留交 LLM 判据兜底；
- Semantic Scholar 无 key 时限速严格，大批量建议 OpenAlex 或 WoS 导出。
