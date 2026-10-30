import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from litreview.batch import (BatchScreener, criteria_from_dict, make_chunks, parse_batch,
                             review_prompt)
from litreview.records import Record


def config(n=2):
    return {
        "domain": "测试领域",
        "criteria": [{"id": "T1", "name": "对象", "question": "符合吗？", "guidance": "纳入：符合\n排除：不符合"}],
        "logic": "all",
    }


def records(n=6):
    return [Record(id=f"WOS:{i:04d}", title=f"Title {i}", abstract="A study of leaching rare earth elements. " * 20) for i in range(n)]


def test_chunk_never_splits_record_and_honors_both_limits():
    rs = records(5)
    chunks = make_chunks(rs, size=2, char_budget=1200)
    assert [r.id for c in chunks for r in c] == [r.id for r in rs]
    assert all(len(c) <= 2 for c in chunks)
    assert all(sum(len(r.title) + len(r.abstract) + 200 for r in c) <= 1200 or len(c) == 1 for c in chunks)


def test_batch_prompt_contains_every_id_once_and_correct_any_rule():
    pack, criteria = criteria_from_dict({**config(), "logic": "any"})
    _, prompt = review_prompt(pack, criteria, records(2), {}, "any")
    assert "任一判据为 Yes" in prompt
    assert prompt.count("ID: WOS:0000") == 1
    assert prompt.count("ID: WOS:0001") == 1


def test_parse_rejects_missing_duplicate_unknown_and_invalid():
    pack, criteria = criteria_from_dict(config())
    rs = records(2)
    valid = {"results": [{"record_id": r.id, "answers": {"T1": "Yes"}, "overall": "Yes"} for r in rs]}
    assert set(parse_batch(valid, rs, criteria, "all")) == {r.id for r in rs}
    for bad in (
        {"results": valid["results"][:1]},
        {"results": valid["results"] + [valid["results"][0]]},
        {"results": valid["results"] + [{"record_id": "wrong", "answers": {"T1": "No"}}]},
        {"results": [{"record_id": rs[0].id, "answers": {"T1": "maybe"}}, valid["results"][1]]},
    ):
        with pytest.raises(ValueError):
            parse_batch(bad, rs, criteria, "all")


def test_three_reviewers_run_before_arbitration_and_keep_all_reasons(monkeypatch):
    class DeliberateDisagreement:
        def __init__(self, spec):
            self.spec = spec
        def complete_json_with_usage(self, system, user):
            ids = [line[4:] for line in user.splitlines() if line.startswith("ID: ")]
            positive = self.spec["name"] != "reviewer_2"
            return {"results": [{"record_id": rid, "answers": {"T1": "Yes" if positive else "No"},
                                 "reasonings": {"T1": "test"}, "overall": "Yes" if positive else "No"}
                                for rid in ids]}, {"input_tokens": 1, "output_tokens": 1}
    monkeypatch.setattr("litreview.batch.make_batch_agent", DeliberateDisagreement)
    pack, criteria = criteria_from_dict(config())
    reviewers = [{"provider": "mock", "name": f"reviewer_{i}", "role": f"reviewer_{i}"} for i in range(1, 4)]
    events = []
    screener = BatchScreener(pack, criteria, reviewers,
                             {"provider": "mock", "name": "arbiter", "role": "arbiter"},
                             chunk_size=2, workers=3, on_phase=lambda *args: events.append(args))
    result = screener.run(records(9))
    assert [e[0] for e in events] == ["reviewing", "arbitrating"]
    assert len(result) == 9
    assert all(len(t["reviews"]) == 3 for t in result.values())
    assert all(t["path"] == "arbitrated" for t in result.values())
    assert all(len(t["final_answers"]) == 1 for t in result.values())


def test_single_reviewer_never_calls_arbiter():
    pack, criteria = criteria_from_dict(config())
    screener = BatchScreener(pack, criteria, [{"provider": "mock", "name": "reviewer_1", "role": "reviewer_1"}],
                             {"provider": "mock", "name": "arbiter", "role": "arbiter"}, chunk_size=5)
    result = screener.run(records(3))
    assert all(t["path"] == "single_reviewer" for t in result.values())
    assert all("arbitration" not in t for t in result.values())


def test_batch_failure_splits_and_only_retries_missing_records():
    class FailForSecond:
        def __init__(self):
            self.requests = []
        def complete_json_with_usage(self, system, user):
            ids = [line[4:] for line in user.splitlines() if line.startswith("ID: ")]
            self.requests.append(ids)
            if "WOS:0001" in ids:
                raise ValueError("simulated bad output")
            return {"results": [{"record_id": rid, "answers": {"T1": "Yes"},
                                 "reasonings": {"T1": "evidence"}} for rid in ids]}, {}
    agent = FailForSecond()
    pack, criteria = criteria_from_dict(config())
    events = []
    screener = BatchScreener(pack, criteria, [{"provider": "mock", "name": "reviewer_1"}],
                             chunk_size=3, on_result=lambda *event: events.append(event))
    outputs = screener._call("review", "reviewer_1", 0, records(3), agent, {}, {})
    assert outputs["WOS:0000"]["overall"] is True
    assert outputs["WOS:0001"]["overall"] is None
    assert outputs["WOS:0002"]["overall"] is True
    assert agent.requests == [["WOS:0000", "WOS:0001", "WOS:0002"], ["WOS:0000"], ["WOS:0001", "WOS:0002"],
                              ["WOS:0001"], ["WOS:0002"]]
    failed = [e for e in events if e[3]["status"] == "failed"]
    assert len(failed) == 1 and failed[0][3]["error"] == "simulated bad output"
    resumed = FailForSecond()
    saved = {"WOS:0000": outputs["WOS:0000"]}
    screener._call("review", "reviewer_1", 1, records(2), resumed, saved, {})
    assert ["WOS:0000"] not in resumed.requests


    pack, criteria = criteria_from_dict(config())
    reviewer = {"provider": "mock", "name": "reviewer_1", "role": "reviewer_1"}
    first = BatchScreener(pack, criteria, [reviewer], chunk_size=2)
    saved = first.run(records(2))
    saved_reviews = {"reviewer_1": {rid: t["reviews"]["reviewer_1"] for rid, t in saved.items()}}
    resumed = BatchScreener(pack, criteria, [reviewer], chunk_size=4,
                            saved_reviews=saved_reviews)
    result = resumed.run(records(2))
    assert result["WOS:0000"]["reviews"]["reviewer_1"] == saved["WOS:0000"]["reviews"]["reviewer_1"]
