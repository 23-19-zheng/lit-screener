from litreview import pipeline
from litreview.records import Record


def screener(mode="precision"):
    cfg = pipeline.load_config("config.yaml")
    cfg["knowledge"], cfg["fewshot"] = {}, {}
    cfg.setdefault("run", {})["mode"] = mode
    s = pipeline.Screener(cfg, mock=True)
    ids = [c.id for c in s.criteria]
    return s, ids


def review(ids, overall, no=()):
    return {"answers": {i: i not in no for i in ids}, "reasonings": {}, "overall": overall}


def test_raw_overall_agreement_with_conflicting_criteria_goes_to_arbitration():
    s, ids = screener()
    reviews = iter([review(ids, True, no=(ids[0],)), review(ids, True)])
    s._review = lambda *a, **k: next(reviews)
    s._arbitrate = lambda *a, **k: {"answers": {i: True for i in ids}, "overall": True}
    t = s.screen_one(Record(id="x", title="t", abstract="a"))
    # A 的逐判据组合为排除、B 为纳入，属于真实分歧，不能不经仲裁直接排除
    assert t["path"] == "arbitrated"
    assert t["final_overall"] is True


def test_precision_mode_sends_arbitrated_disputes_to_human_review():
    s, ids = screener("precision")
    reviews = iter([review(ids, True), review(ids, False, no=ids)])
    s._review = lambda *a, **k: next(reviews)
    s._arbitrate = lambda *a, **k: {"answers": {i: True for i in ids}, "overall": True}
    t = s.screen_one(Record(id="y", title="t", abstract="a"))
    assert t["path"] == "arbitrated"
    assert t["human_review"] is True and t["review_reason"] == "评审分歧"


def test_run_writes_trace_incrementally_and_resumes(tmp_path):
    import json
    s, _ = screener()
    records = [Record(id=f"r{i}", title=f"t{i}", abstract="a") for i in range(3)]
    calls, interrupted = [], []
    real = s.screen_one

    def counting(r):
        calls.append(r.id)
        if r.id == "r2" and not interrupted:
            interrupted.append(True)
            raise KeyboardInterrupt  # 模拟进程在第 3 篇时被中断
        return real(r)

    s.screen_one = counting
    s.cfg.setdefault("run", {})["threads"] = 1
    try:
        s.run(records, out_dir=str(tmp_path))
    except KeyboardInterrupt:
        pass
    trace = next(tmp_path.glob("trace_*.jsonl"))
    with open(trace, "a", encoding="utf-8") as f:
        f.write('{"record": {"id": "r2"')  # 崩溃时写了半行
    assert [json.loads(l)["record"]["id"] for l in trace.read_text().splitlines()[:2]] == ["r0", "r1"]

    calls.clear()
    summary = s.run(records, out_dir=str(tmp_path), resume=str(trace))
    assert calls == ["r2"]  # 只补跑未完成的
    lines = [json.loads(l) for l in trace.read_text().splitlines()]
    assert sorted(t["record"]["id"] for t in lines) == ["r0", "r1", "r2"]
    assert summary["stats"]["total"] == 3


def test_resume_reruns_records_that_errored(tmp_path):
    import json
    s, _ = screener()
    trace = tmp_path / "trace_x.jsonl"
    trace.write_text(json.dumps({"record": {"id": "r0"}, "path": "error"}) + "\n")
    calls = []
    real = s.screen_one
    s.screen_one = lambda r: calls.append(r.id) or real(r)
    s.run([Record(id="r0", title="t", abstract="a")], out_dir=str(tmp_path), resume=str(trace))
    assert calls == ["r0"]
