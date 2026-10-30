# -*- coding: utf-8 -*-
"""领域知识库：Markdown 条目加载 + TF-IDF 语义检索（RAG 注入源）。"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


@dataclass
class KnowledgeEntry:
    title: str
    body: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


def load_entries(kb_dir: str) -> list[KnowledgeEntry]:
    """加载目录下所有 .md 文件，以 '## ' 标题切分条目。"""
    entries: list[KnowledgeEntry] = []
    for path in sorted(glob.glob(os.path.join(kb_dir, "*.md"))):
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
        entries.extend(parse_entries(content))
    return entries


def parse_entries(content: str) -> list[KnowledgeEntry]:
    """从上传或粘贴的 Markdown 构造知识条目。"""
    entries = []
    for block in content.split("\n## "):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        first = lines[0].lstrip("# ").strip()
        body = "\n".join(lines[1:]).strip()
        if first or body:
            entries.append(KnowledgeEntry(title=first, body=body))
    return entries


class KnowledgeRetriever:
    """字符级 TF-IDF 检索器，中英文混排可用。"""

    def __init__(self, entries: list[KnowledgeEntry], top_k: int = 4):
        if not entries:
            raise ValueError("知识库为空：knowledge 目录下没有可用条目")
        self.entries = entries
        self.top_k = top_k
        self._vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4))
        self._mat = self._vec.fit_transform([e.text for e in entries])

    def retrieve(self, query: str, top_k: int | None = None) -> list[KnowledgeEntry]:
        k = top_k or self.top_k
        sims = cosine_similarity(self._vec.transform([query]), self._mat)[0]
        order = sims.argsort()[::-1][:k]
        return [self.entries[i] for i in order if sims[i] > 0]

    def format_for_prompt(self, entries: list[KnowledgeEntry]) -> str:
        lines = []
        for i, e in enumerate(entries, 1):
            body = e.body if len(e.body) <= 500 else e.body[:500] + "…"
            lines.append(f"{i}. {e.title}: {body}")
        return "\n".join(lines)
