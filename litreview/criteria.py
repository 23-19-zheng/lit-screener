# -*- coding: utf-8 -*-
"""判据包加载与组合逻辑。"""
from __future__ import annotations

from dataclasses import dataclass

import yaml


@dataclass
class Criterion:
    id: str
    name: str
    question: str
    guidance: str


@dataclass
class CriteriaPack:
    pack: str
    description: str
    criteria: list[Criterion]
    domain: str = "相关领域"    # 用于评审 system prompt 的领域身份

    def get(self, cid: str) -> Criterion:
        for c in self.criteria:
            if c.id == cid:
                return c
        raise KeyError(f"判据包 {self.pack} 中不存在判据 {cid}")


def load_pack(path: str, active: list[str] | None = None) -> tuple[CriteriaPack, list[Criterion]]:
    """加载判据包；active 指定本次启用的判据子集（None=全部）。

    返回 (完整包, 启用判据列表)。active 中出现包里不存在的 id 会报错。
    """
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    criteria = [Criterion(
        id=c["id"],
        name=c.get("name", c["id"]),
        question=c["question"].strip(),
        guidance=(c.get("guidance") or "").strip(),
    ) for c in data["criteria"]]
    pack = CriteriaPack(pack=data.get("pack", path),
                        description=data.get("description", ""),
                        criteria=criteria,
                        domain=(data.get("domain") or "相关领域").strip())
    if active is None:
        selected = list(criteria)
    else:
        missing = [a for a in active if a not in {c.id for c in criteria}]
        if missing:
            raise ValueError(f"active 判据在判据包中不存在: {missing}")
        selected = [pack.get(a) for a in active]
    if not selected:
        raise ValueError("未选择任何判据")
    return pack, selected


def combine(answers: dict[str, bool | None], logic: str) -> bool | None:
    """按组合逻辑由逐判据答案得到整体纳入判定。

    返回 None 表示有判据未解析成功，无法组合。
    """
    vals = list(answers.values())
    if any(v is None for v in vals):
        return None
    if logic == "all":
        return all(vals)
    if logic == "any":
        return any(vals)
    raise ValueError(f"未知组合逻辑: {logic}（支持 all/any）")
