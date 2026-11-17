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
