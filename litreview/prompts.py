# -*- coding: utf-8 -*-
"""评审/仲裁 prompt 构建 + 结构化输出解析。

输出格式仿 Wang et al. (Water Research 2026) Text S11/S12 模板：
  Response <判据id>: Yes/No
  Reasoning <判据id>: <引文证据+解释>
  Overall Response: Yes/No
  Reasoning: <总推理>
仲裁输出：
  Final <判据id>: Yes/No
  Final Overall: Yes/No
  Disagreement Root: <分歧根源>

解析器对"合并成一行"的形式（如 `Response T1, T2, T3: Yes, Yes, Yes`）做了容错。
"""
from __future__ import annotations

import re

from .criteria import CriteriaPack, Criterion
from .records import Record

def system_reviewer(domain: str = "相关领域") -> str:
    return (
        f"你是{domain}的资深文献筛选专家。你的任务是根据给定的筛选判据，"
        "逐条独立评估一篇文献（仅提供标题与摘要），并给出结构化判定。\n"
        "要求：\n"
        "1. 每条判据独立回答 Yes/No，并给出基于原文的引文证据或明确解释；\n"
        "2. 所有判断必须可由标题、摘要或所提供的领域背景知识验证，禁止臆测；\n"
        "3. 判据未提及或信息不足时从严判断（倾向 No）并在理由中说明信息不足；\n"
        "4. 严格按指定格式输出，不要输出格式之外的任何内容。"
    )


# 兼容旧引用（领域身份请优先在判据包 domain 字段中配置）
SYSTEM_REVIEWER = system_reviewer("相关领域")

SYSTEM_ARBITER = (
    "你是文献筛选仲裁专家。两位评审对同一篇文献给出了不一致的判定，"
    "请对比题录信息与双方的逐条判定及推理链，找出分歧根源，判断谁的推理更符合"
    "筛选判据与领域知识，并给出最终裁定。\n"
    "要求：\n"
    "1. 逐条判据给出最终裁定（可支持任一方，也可两方都错）；\n"
    "2. 判断必须可由题录或背景知识验证，禁止臆测；\n"
    "3. 严格按指定格式输出。"
)


def _render_format_example(criteria: list[Criterion], prefix: str) -> str:
    """生成逐判据的输出格式示例（避免模型把多判据合并成一行）。"""
    lines = []
    for c in criteria:
        lines.append(f"{prefix} {c.id}: Yes/No")
        lines.append(f"Reasoning {c.id}: <引文证据与解释>")
    if prefix == "Response":
        lines.append("Overall Response: Yes/No")
        lines.append("Reasoning: <总推理>")
    else:
        lines.append("Final Overall: Yes/No")
        lines.append("Disagreement Root: <分歧根源分析>")
    return "\n".join(lines)


def build_reviewer_prompt(pack: CriteriaPack, criteria: list[Criterion],
                          record: Record, knowledge_text: str = "",
                          fewshot_text: str = "", output_mode: str = "text") -> str:
    crit_blocks = []
    for c in criteria:
        block = f"[{c.id}] {c.name}\n判定问题: {c.question}"
        if c.guidance:
            block += f"\n判定指引:\n{c.guidance}"
        crit_blocks.append(block)
    parts = [
        "请根据以下筛选判据评估文献：",
        "\n\n".join(crit_blocks),
        f"\n整体判定规则: 只有当{'全部' if len(criteria) > 1 else '该'}判据为 Yes 时，"
        f"Overall Response 才为 Yes（本次启用判据: {', '.join(c.id for c in criteria)}）。",
        f"\n文献信息:\nTitle: {record.title}\nAbstract: {record.abstract or '（无摘要）'}",
    ]
    if fewshot_text:
        parts.append(f"\n人工已裁定的参考案例（判定口径对齐用，勿照抄结论）:\n{fewshot_text}")
    if knowledge_text:
        parts.append(f"\n领域背景知识（判定术语与技术边界时参考）:\n{knowledge_text}")
    if output_mode == "json":
        parts.append("\n输出要求: 仅输出一个 JSON 对象（不要 markdown 代码块、不要任何其他文字），"
                     "结构如下:\n" + _review_json_spec(criteria))
    else:
        parts.append("\n输出格式（严格遵守，每条判据单独一行作答，不要合并判据，"
                     "不要输出格式之外的任何内容）:\n"
                     + _render_format_example(criteria, "Response"))
    return "\n".join(parts)


def _review_json_spec(criteria: list[Criterion]) -> str:
    answers = ", ".join(f'"{c.id}": "Yes/No"' for c in criteria)
    reasonings = ", ".join(f'"{c.id}": "<该判据的引文证据与解释>"' for c in criteria)
    return ('{\n  "answers": {' + answers + '},\n'
            '  "reasonings": {' + reasonings + '},\n'
            '  "overall": "Yes/No"\n}')


def build_arbiter_prompt(pack: CriteriaPack, criteria: list[Criterion], record: Record,
                         out_a: dict, out_b: dict, knowledge_text: str = "",
                         output_mode: str = "text") -> str:
    def render(name: str, out: dict) -> str:
        lines = [f"{name} 判定: Overall: {out.get('overall')}"]
        for c in criteria:
            ans = (out.get("answers") or {}).get(c.id)
            rs = (out.get("reasonings") or {}).get(c.id, "")
            lines.append(f"  {c.id}: {ans} | {rs}")
        return "\n".join(lines)

    parts = [
        f"筛选判据（{', '.join(c.id for c in criteria)}）:",
        "\n".join(f"[{c.id}] {c.name}: {c.question}" for c in criteria),
        f"\n文献信息:\nTitle: {record.title}\nAbstract: {record.abstract or '（无摘要）'}",
        f"\n评审一:\n{render('Reviewer-A', out_a)}",
        f"\n评审二:\n{render('Reviewer-B', out_b)}",
    ]
    if knowledge_text:
        parts.append(f"\n领域背景知识:\n{knowledge_text}")
    if output_mode == "json":
        answers = ", ".join(f'"{c.id}": "Yes/No"' for c in criteria)
        parts.append("\n输出要求: 仅输出一个 JSON 对象（不要 markdown 代码块、不要任何其他文字），"
                     "结构如下:\n"
                     '{\n  "answers": {' + answers + '},\n'
                     '  "overall": "Yes/No",\n'
                     '  "disagreement_root": "<分歧根源分析>"\n}')
    else:
        parts.append("\n输出格式（严格遵守，每条判据单独一行作答，不要合并判据）:\n"
                     + _render_format_example(criteria, "Final"))
    return "\n".join(parts)


# ---------------------------------------------------------------- 解析

def _yn(s) -> bool | None:
    if isinstance(s, bool):
        return s
    s = str(s).strip().lower()
    if s.startswith(("y", "true", "1")) or s in ("是", "纳入"):
        return True
    if s.startswith(("n", "false", "0")) or s in ("否", "排除"):
        return False
    return None


def _parse_merged_line(text: str, prefix: str) -> dict[str, bool | None]:
    """容错：解析合并形式 `Response T1, T2, T3: Yes, Yes, No`（含中文顿号）。

    返回 {cid: value}；仅当判据数与答案数一致时才采信。
    """
    out: dict[str, bool | None] = {}
    for m in re.finditer(rf"{prefix}\s+([\w\s,，、]+?)\s*[:：]\s*([^\n]+)", text):
        ids = [i.strip() for i in re.split(r"[,，、\s]+", m.group(1)) if i.strip()]
        raw = m.group(2)
        vals = [v.strip() for v in re.split(r"[,，、]+", raw) if v.strip()]
        if len(ids) > 1 and len(ids) == len(vals) and all(
                re.fullmatch(r"\w+", i) for i in ids):
            for i, v in zip(ids, vals):
                out[i] = _yn(v)
    return out


def parse_review_output(text: str, criteria_ids: list[str]) -> dict:
    """解析评审输出。answers/overall 中解析失败项为 None。"""
    answers, reasonings = {}, {}
    for cid in criteria_ids:
        m = re.search(rf"Response\s+{re.escape(cid)}\s*[:：]\s*(\S+)", text, re.I)
        answers[cid] = _yn(m.group(1)) if m else None
        rm = re.search(rf"Reasoning\s+{re.escape(cid)}\s*[:：]\s*(.+?)(?=\nResponse\s|\nOverall\s|\Z)",
                       text, re.I | re.S)
        reasonings[cid] = rm.group(1).strip() if rm else ""
    if all(v is None for v in answers.values()):
        merged = _parse_merged_line(text, "Response")
        if merged:
            answers.update({cid: merged.get(cid) for cid in criteria_ids})
    m = re.search(r"Overall\s+Response\s*[:：]\s*(\S+)", text, re.I)
    overall = _yn(m.group(1)) if m else None
    return {"answers": answers, "reasonings": reasonings, "overall": overall,
            "raw": text}


def parse_arbiter_output(text: str, criteria_ids: list[str]) -> dict:
    answers = {}
    for cid in criteria_ids:
        m = re.search(rf"Final\s+{re.escape(cid)}\s*[:：]\s*(\S+)", text, re.I)
        answers[cid] = _yn(m.group(1)) if m else None
    if all(v is None for v in answers.values()):
        merged = _parse_merged_line(text, "Final")
        if merged:
            answers.update({cid: merged.get(cid) for cid in criteria_ids})
    m = re.search(r"Final\s+Overall\s*[:：]\s*(\S+)", text, re.I)
    overall = _yn(m.group(1)) if m else None
    rm = re.search(r"Disagreement\s+Root\s*[:：]\s*(.+)", text, re.I | re.S)
    return {"answers": answers, "overall": overall,
            "root": rm.group(1).strip() if rm else "", "raw": text}


# ---------------------------------------------------------------- JSON 输出解析

def parse_json_review(data, criteria_ids: list[str]) -> dict | None:
    """解析结构化输出的评审结果；结构不符返回 None（调用方回退文本模式）。"""
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        return None
    answers = {cid: _yn(data["answers"].get(cid)) for cid in criteria_ids}
    rsrc = data.get("reasonings")
    reasonings = {cid: (str(rsrc.get(cid, "")).strip() if isinstance(rsrc, dict) else "")
                  for cid in criteria_ids}
    overall = _yn(data.get("overall"))
    if all(v is None for v in answers.values()) and overall is None:
        return None
    return {"answers": answers, "reasonings": reasonings, "overall": overall, "raw": data}


def parse_json_arbiter(data, criteria_ids: list[str]) -> dict | None:
    if not isinstance(data, dict) or not isinstance(data.get("answers"), dict):
        return None
    answers = {cid: _yn(data["answers"].get(cid)) for cid in criteria_ids}
    overall = _yn(data.get("overall"))
    if all(v is None for v in answers.values()) and overall is None:
        return None
    return {"answers": answers, "overall": overall,
            "root": str(data.get("disagreement_root", "")).strip(), "raw": data}
