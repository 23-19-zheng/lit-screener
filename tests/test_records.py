from pathlib import Path

from litreview.records import assign_record_ids, dedupe, load_records

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
