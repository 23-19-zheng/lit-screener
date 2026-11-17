from pathlib import Path

import pytest

from litreview.records import Record, assign_record_ids, dedupe, load_records

ATTACHMENT = Path("/Users/zhengchao/Desktop/稀土浸出物质筛选相关文献")


def test_wos_tagged_multiline_and_ris_stable_id(tmp_path):
    text = """FN Clarivate Analytics Web of Science
VR 1.0
PT J
AU One, A
   Two, B
TI A title over
   two lines
DT Article
AB Abstract over
   two lines
PY 2024
DI 10.1000/test
LA English
UT WOS:000001
ER
EF
"""
    ris = """TY  - JOUR
TI  - A title over two lines
AB  - Abstract over two lines
PY  - 2024
DO  - 10.1000/test
AN  - WOS:000001
ER  -
"""
    txt = tmp_path / "one.txt"
    ris_file = tmp_path / "one.ris"
    txt.write_text(text)
    ris_file.write_text(ris)
    a, b = load_records(str(txt))[0], load_records(str(ris_file))[0]
    assert a.title == "A title over two lines"
    assert a.abstract == "Abstract over two lines"
    assert a.authors == "One, A; Two, B"
    assert a.doctype == "Article"
    assert a.id == b.id == "WOS:000001"
    assert len(dedupe([a, b])) == 1


@pytest.mark.skipif(not ATTACHMENT.exists(), reason="依赖本机附件目录")
def test_dedupe_matches_doi_record_to_title_only_record():
    a = assign_record_ids(load_records(str(ATTACHMENT / "RIS格式/5001-5117.ris")))[0]
    b = type(a)(id="other", title=a.title, abstract="A much longer abstract " * 200)
    merged = dedupe([a, b])
    assert len(merged) == 1
    assert merged[0].abstract == b.abstract


def test_attachment_both_formats_contain_same_5117_wos_records():
    if not ATTACHMENT.exists():
        return
    ris, txt = [], []
    for kind, target in (("RIS格式", ris), ("TXT格式", txt)):
        for path in sorted((ATTACHMENT / kind).glob("*.*")):
            target.extend(load_records(str(path)))
    assert len(ris) == len(txt) == 5117
    assert [r.external_id for r in ris] == [r.external_id for r in txt]
    assert [r.abstract for r in ris] == [r.abstract for r in txt]
    assert len(assign_record_ids(dedupe(ris))) == 5116
    assert sum(not r.abstract for r in ris) == 3
    assert sum("review" in r.doctype.lower() for r in txt) == 322


def test_ris_endnote_tags_t1_n2_y1(tmp_path):
    ris = tmp_path / "endnote.ris"
    ris.write_text("TY  - JOUR\nT1  - Real Paper Title\nT2  - Journal of Hydrometallurgy\n"
                   "N2  - This is the abstract.\nY1  - 2020/05/12/\nER  - \n")
    r = load_records(str(ris))[0]
    assert r.title == "Real Paper Title"
    assert r.abstract == "This is the abstract."
    assert r.year == "2020"


def test_dedupe_keeps_same_title_with_different_dois():
    a = Record(id="a", title="Editorial", doi="10.1/aaa")
    b = Record(id="b", title="Editorial", doi="10.1/bbb")
    c = Record(id="c", title="Editorial")
    merged = dedupe([a, b, c])
    assert sorted(r.doi for r in merged) == ["10.1/aaa", "10.1/bbb"]


class _FakeResp:
    def __init__(self, status, data=None):
        self.status_code, self._data = status, data or {}

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get(self, url, params=None, **kw):
        self.calls.append(params)
        return self.responses.pop(0) if self.responses else _FakeResp(429)


def _patch_session(monkeypatch, responses):
    import litreview.records as records_module
    session = _FakeSession(responses)
    monkeypatch.setattr(records_module.requests, "Session", lambda: session)
    monkeypatch.setattr("time.sleep", lambda s: None)
    return session


def test_semantic_scholar_gives_up_after_repeated_rate_limits(monkeypatch):
    import pytest
    from litreview.records import fetch_semantic_scholar
    session = _patch_session(monkeypatch, [])
    with pytest.raises(RuntimeError, match="429"):
        fetch_semantic_scholar("q", max_records=10)
    assert len(session.calls) <= 5


def test_openalex_date_filters_combine_without_duplicates(monkeypatch):
    from litreview.records import fetch_openalex
    empty = {"results": [], "meta": {}}
    session = _patch_session(monkeypatch, [_FakeResp(200, empty)] * 3)
    fetch_openalex("q", from_year=2015, date_to="2024")
    fetch_openalex("q", from_year=2015, date_from="2020")
    fetch_openalex("q", from_year=2021, date_from="2020-06-01")
    filters = [p["filter"] for p in session.calls]
    assert filters == [
        "from_publication_date:2015-01-01,to_publication_date:2024-12-31",
        "from_publication_date:2020-01-01",
        "from_publication_date:2021-01-01",
    ]
