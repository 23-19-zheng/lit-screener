import json

from litreview.web.audit import audit_rows, audit_summary, error_groups, render_html


def trace(rid, a, b, path, overall=None, t1diff=False):
    return {"record_id": rid, "record": {"title": f"Paper {rid}", "doi": "", "year": "2024", "abstract": "Abstract"},
            "criteria": ["T1", "T2"], "path": path, "final_overall": overall,
            "reviews": {"reviewer_1": {"overall": a, "answers": {"T1": a, "T2": True}, "reasonings": {"T1": "理由 A"}},
                        "reviewer_2": {"overall": b, "answers": {"T1": not a if t1diff else a, "T2": True}, "reasonings": {"T1": "理由 B"}}}}


def test_audit_distinguishes_overall_and_criterion_disagreement():
    rows = [trace("a", True, True, "consistent", True),
            trace("b", False, False, "consistent", False, t1diff=True),
            trace("c", True, False, "arbitration_error"),
            trace("d", False, True, "arbitrated", True, t1diff=True)]
    summary = audit_summary(rows)
    assert summary["consistent"] == 2
    assert summary["overall_disagreement"] == 2
    assert summary["criterion_disagreement"] == 2
    assert summary["arbitrated"] == 1
    assert summary["arbitration_failed"] == 1
    assert [r["record_id"] for r in audit_rows(rows, "overall")] == ["c", "d"]
    assert [r["record_id"] for r in audit_rows(rows, "criteria")] == ["b", "d"]


def test_html_report_is_human_readable_and_escapes_content():
    t = trace("x", True, False, "arbitration_error")
    t["record"]["title"] = "<unsafe> title"
    task = {"id": "run_test", "name": "测试审计", "config": {"criteria": {"domain": "稀土", "logic": "all", "criteria": []},
            "reviewers": [{"name": "reviewer_1", "model": "A"}, {"name": "reviewer_2", "model": "B"}],
            "arbiter": {"model": "C", "temperature": 1}, "filters": {"language": "en"}}}
    content = render_html(task, [t], [{"kind": "arbitration", "reviewer": "arbiter", "chunk_index": 1,
                                     "status": "failed", "error": "temperature only 1", "usage": {}}])
    assert "仲裁失败" in content and "理由 A" in content and "temperature only 1" in content
    assert "<unsafe> title" not in content and "&lt;unsafe&gt; title" in content
