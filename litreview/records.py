# -*- coding: utf-8 -*-
"""统一题录模型与多数据源适配器。"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field, asdict

import requests


@dataclass
class Record:
    id: str
    title: str
    abstract: str = ""
    authors: str = ""
    year: str = ""
    doi: str = ""
    source: str = ""
    language: str = ""    # 归一化 ISO 639-1（如 en），未知为空
    doctype: str = ""     # 出版类型原文（article/review/...），来源间口径不一
    date: str = ""        # 归一化 ISO 日期（yyyy / yyyy-mm / yyyy-mm-dd），未知为空

    def to_dict(self):
        return asdict(self)


# 常见语种全称 → ISO 639-1（WoS/RIS 用全称，OpenAlex/S2 用二字母码）
_LANG_MAP = {
    "english": "en", "chinese": "zh", "japanese": "ja", "german": "de",
    "french": "fr", "spanish": "es", "russian": "ru", "portuguese": "pt",
    "korean": "ko", "italian": "it", "polish": "pl", "turkish": "tr",
    "dutch": "nl", "persian": "fa", "ukrainian": "uk", "arabic": "ar",
    "czech": "cs", "swedish": "sv", "hungarian": "hu", "malay": "ms",
}


def norm_language(v: str) -> str:
    """语种归一化：English/english → en；已是二字母码原样返回；未知返回小写原文。"""
    v = (v or "").strip().lower()
    if not v:
        return ""
    if len(v) == 2:
        return v
    return _LANG_MAP.get(v, v)


def _norm_date(v: str, year: str = "") -> str:
    """日期归一化为 yyyy / yyyy-mm / yyyy-mm-dd；解析失败回退 year。"""
    v = (v or "").strip()
    m = re.search(r"(\d{4})[-/.年](\d{1,2})(?:[-/.月](\d{1,2}))?", v)
    if m:
        y, mo, d = m.group(1), int(m.group(2)), m.group(3)
        if 1 <= mo <= 12:
            out = f"{y}-{mo:02d}"
            if d and 1 <= int(d) <= 31:
                out += f"-{int(d):02d}"
            return out
    m = re.search(r"^(\d{4})$", v)
    if m:
        return m.group(1)
    return (year or "").strip()


def _norm_title(title: str) -> str:
    s = unicodedata.normalize("NFKC", title or "").lower()
    return re.sub(r"[^a-z0-9一-鿿]+", "", s)


def dedupe(records: list[Record]) -> list[Record]:
    """DOI 优先，标题归一化兜底。"""
    seen: dict[str, Record] = {}
    out = []
    for r in records:
        key = ("doi", r.doi.lower()) if r.doi else ("title", _norm_title(r.title))
        if not key[1]:
            out.append(r)  # 无任何标识，不去重
            continue
        if key in seen:
            continue
        seen[key] = r
        out.append(r)
    return out


# ---------------------------------------------------------------- 文件适配器

def load_records(path: str) -> list[Record]:
    """按文件内容自动识别格式：RIS / WoS 制表符 / 通用 CSV。"""
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        head = f.read(4096)
    if re.search(r"^TY\s{1,2}-\s", head, re.M):
        return load_ris(path)
    if "\t" in head.splitlines()[0] if head.strip() else False:
        return load_wos_tab(path)
    return load_csv(path)


def load_ris(path: str) -> list[Record]:
    records, cur, key, buf = [], {}, None, []

    def flush():
        if not cur:
            return
        title = (cur.get("TI") or cur.get("T2") or [""])[0]
        year = (cur.get("PY", [""])[0]).strip()
        records.append(Record(
            id=f"ris-{len(records)+1}",
            title=title,
            abstract=" ".join(cur.get("AB", [])),
            authors="; ".join(cur.get("AU", [])),
            year=year,
            doi=(cur.get("DO", [""])[0]).strip(),
            source="ris",
            language=norm_language((cur.get("LA", [""])[0])),
            doctype=(cur.get("TY", [""])[0]).strip(),
            date=_norm_date((cur.get("DA", [""])[0]), year),
        ))

    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            m = re.match(r"^([A-Z0-9]{2})\s{1,2}-\s?(.*)$", line.rstrip("\n"))
            if m:
                if m.group(1) == "ER":
                    flush()
                    cur, key = {}, None
                    continue
                key = m.group(1)
                cur.setdefault(key, []).append(m.group(2).strip())
            elif key and line.startswith("  "):
                cur[key][-1] += " " + line.strip()
    flush()
    return records


_WOS_COLS = {"title": ["Article Title", "Document Title", "Title"],
             "abstract": ["Abstract"],
             "authors": ["Authors"],
             "year": ["Publication Year", "Year"],
             "doi": ["DOI"],
             "language": ["Language", "Languages"],
             "doctype": ["Document Type", "Publication Type"],
             "date": ["Publication Date", "Issue Date"]}


def load_wos_tab(path: str) -> list[Record]:
    return _load_tabular(path, delimiter="\t")


def load_csv(path: str) -> list[Record]:
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        sample = f.read(2048)
    delim = ";" if sample.count(";") > sample.count(",") else ","
    return _load_tabular(path, delimiter=delim)


def _pick(cols: list[str], candidates: list[str]) -> str | None:
    for c in candidates:
        if c in cols:
            return c
    lowered = {c.lower().strip(): c for c in cols}
    for c in candidates:
        if c.lower().strip() in lowered:
            return lowered[c.lower().strip()]
    return None


def _load_tabular(path: str, delimiter: str) -> list[Record]:
    records = []
    with open(path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.DictReader(f, delimiter=delimiter)
        cols = reader.fieldnames or []
    ct = _pick(cols, _WOS_COLS["title"])
    ca = _pick(cols, _WOS_COLS["abstract"])
    cu = _pick(cols, _WOS_COLS["authors"])
    cy = _pick(cols, _WOS_COLS["year"])
    cd = _pick(cols, _WOS_COLS["doi"])
    clang = _pick(cols, _WOS_COLS["language"])
    ctype = _pick(cols, _WOS_COLS["doctype"])
    cdate = _pick(cols, _WOS_COLS["date"])
    if not ct:
        raise ValueError(f"文件 {path} 中找不到标题列，现有列: {cols}")
    for i, row in enumerate(reader, 1):
        if not (row.get(ct) or "").strip():
            continue
        year = str(row.get(cy) or "").strip() if cy else ""
        records.append(Record(
            id=f"row-{i}",
            title=(row.get(ct) or "").strip(),
            abstract=(row.get(ca) or "").strip() if ca else "",
            authors=(row.get(cu) or "").strip() if cu else "",
            year=year,
            doi=(row.get(cd) or "").strip() if cd else "",
            source="file",
            language=norm_language((row.get(clang) or "")) if clang else "",
            doctype=(row.get(ctype) or "").strip() if ctype else "",
            date=_norm_date((row.get(cdate) or ""), year) if cdate else year,
        ))
    return records


# ---------------------------------------------------------------- API 适配器

def _reconstruct_abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def fetch_openalex(query: str, from_year: int | None = None,
                   max_records: int = 500, mailto: str = "",
                   date_from: str = "", date_to: str = "",
                   api_key: str = "") -> list[Record]:
    """OpenAlex 检索（免费）。cursor 翻页自 2025 起需免费 API key（openalex.org/settings/api），
    无 key 时仅能取第一页（≤200 条）。date_from/date_to 为 ISO 日期或年份。"""
    base = "https://api.openalex.org/works"
    filt = []
    if date_from:
        filt.append(f"from_publication_date:{date_from}")
    if date_to:
        filt.append(f"to_publication_date:{date_to}")
    elif from_year:
        filt.append(f"from_publication_date:{from_year}-01-01")
    records, cursor = [], "*"
    import time
    with requests.Session() as s:
        while len(records) < max_records:
            params = {"search": query, "per-page": min(200, max_records - len(records)),
                      "cursor": cursor}
            if filt:
                params["filter"] = ",".join(filt)
            if mailto:
                params["mailto"] = mailto
            if api_key:
                params["api_key"] = api_key
            for delay in [0, 3, 8]:  # 限流（429/401）退避重试
                if delay:
                    time.sleep(delay)
                resp = s.get(base, params=params, timeout=60)
                if resp.status_code in (401, 429):
                    continue
                break
            resp.raise_for_status()
            data = resp.json()
            time.sleep(0.5)  # 礼貌间隔
            for w in data.get("results", []):
                authorships = w.get("authorships") or []
                authors = "; ".join(a["author"]["display_name"]
                                    for a in authorships[:10] if a.get("author"))
                records.append(Record(
                    id=w["id"].rsplit("/", 1)[-1],
                    title=(w.get("title") or "").strip(),
                    abstract=_reconstruct_abstract(w.get("abstract_inverted_index")),
                    authors=authors,
                    year=str(w.get("publication_year") or ""),
                    doi=(w.get("doi") or "").replace("https://doi.org/", ""),
                    source="openalex",
                    language=norm_language(w.get("language") or ""),
                    doctype=(w.get("type") or "").strip(),
                    date=(w.get("publication_date") or "").strip(),
                ))
            cursor = data.get("meta", {}).get("next_cursor")
            if not cursor or not data.get("results"):
                break
    return records


def fetch_semantic_scholar(query: str, from_year: int | None = None,
                           max_records: int = 500, api_key_env: str = "S2_API_KEY") -> list[Record]:
    """Semantic Scholar 检索（无 key 限速 100 次/5 分钟）。"""
    import os
    headers = {}
    key = os.environ.get(api_key_env)
    if key:
        headers["x-api-key"] = key
    fields = "title,abstract,year,externalIds,authors,language,publicationTypes,publicationDate"
    records, offset = [], 0
    with requests.Session() as s:
        while len(records) < max_records:
            params = {"query": query, "fields": fields, "limit": min(100, max_records - len(records)),
                      "offset": offset}
            if from_year:
                params["year"] = f"{from_year}-"
            resp = s.get("https://api.semanticscholar.org/graph/v1/paper/search",
                         params=params, headers=headers, timeout=60)
            if resp.status_code == 429:
                import time
                time.sleep(5)
                continue
            resp.raise_for_status()
            data = resp.json()
            for p in data.get("data", []):
                year = str(p.get("year") or "")
                records.append(Record(
                    id=p.get("paperId") or f"s2-{len(records)+1}",
                    title=(p.get("title") or "").strip(),
                    abstract=(p.get("abstract") or "").strip(),
                    authors="; ".join(a["name"] for a in (p.get("authors") or [])[:10]),
                    year=year,
                    doi=((p.get("externalIds") or {}).get("DOI") or ""),
                    source="semantic_scholar",
                    language=norm_language(p.get("language") or ""),
                    doctype=";".join(p.get("publicationTypes") or []),
                    date=_norm_date(p.get("publicationDate") or "", year),
                ))
            got = len(data.get("data") or [])
            offset += got
            if got == 0 or not data.get("next"):
                break
    return records
