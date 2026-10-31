import time

import pytest
from fastapi.testclient import TestClient

from litreview.web import app as web_module
from litreview.web.app import app
from litreview.web.runner import TaskRunner
from litreview.web.store import Store


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    fresh = Store(tmp_path / "test.db")
    monkeypatch.setattr(web_module, "store", fresh)
    runner = TaskRunner(fresh)
    monkeypatch.setattr(web_module, "runner", runner)
    monkeypatch.setattr(fresh, "UPLOADS", tmp_path / "uploads", raising=False)
    yield fresh
    for task in fresh.list_tasks():
        runner.cancel(task["id"])
    for thread in runner.threads.values():
        thread.join(timeout=5)


def wait(client, tid):
    for _ in range(100):
        task = client.get(f"/api/tasks/{tid}").json()
        if task["status"] in {"completed", "failed", "cancelled"}:
            return task
        time.sleep(.05)
    raise TimeoutError("Mock task did not finish")


def test_web_upload_multi_part_screen_export_and_compare(tmp_path):
    with TestClient(app) as client:
        ris = """TY  - JOUR\nTI  - Leaching rare earth\nAB  - Experimental recovery of rare earth.\nPY  - 2025\nAN  - WOS:001\nER  -\n"""
        files = [("files", ("1.ris", ris, "text/plain")),
                 ("files", ("2.ris", ris.replace("WOS:001", "WOS:002").replace("Leaching rare earth", "Different article"), "text/plain"))]
        uploaded = client.post("/api/datasets", files=files)
        assert uploaded.status_code == 200, uploaded.text
        dataset = uploaded.json()["dataset"]
        assert dataset["stats"]["raw"] == dataset["stats"]["unique"] == 2
        criteria = {"domain": "稀土", "logic": "all", "criteria": [
            {"id": "T1", "name": "对象", "question": "是否回收稀土？", "guidance": "纳入：回收"}]}
        def payload(name):
            return {"name": name, "dataset_id": dataset["id"], "knowledge": "## 稀土\n包括镧系元素。",
                    "config": {"criteria": criteria, "chunk_size": 2, "workers": 2,
                               "reviewers": [{"provider": "mock", "model": "mock-model", "name": f"reviewer_{i}", "role": f"reviewer_{i}"} for i in range(1, 3)],
                               "arbiter": {"provider": "mock", "model": "mock-arbiter", "name": "arbiter", "role": "arbiter"}}}
        t1 = client.post("/api/tasks", json=payload("双评审测试"))
        assert t1.status_code == 201, t1.text
        tid = t1.json()["id"]
        assert wait(client, tid)["status"] == "completed"
        results = client.get(f"/api/tasks/{tid}/results").json()
        assert results["total"] == 2
        assert len(results["items"][0]["reviews"]) == 2
        assert client.get(f"/api/tasks/{tid}/export/include").status_code == 200
        assert client.get(f"/api/tasks/{tid}/export/trace").status_code == 200
        p = payload("单评审测试")
        p["config"]["reviewers"] = p["config"]["reviewers"][:1]
        p["config"]["arbiter"] = None
        t2 = client.post("/api/tasks", json=p).json()
        assert wait(client, t2["id"])["status"] == "completed"
        comparison = client.get(f"/api/compare?ids={tid},{t2['id']}").json()
        assert comparison[0]["pair_agreement"] is not None
        cloned = client.post(f"/api/tasks/{tid}/clone").json()
        assert cloned["config"]["reviewers"] == payload("x")["config"]["reviewers"]


def test_runner_resume_uses_saved_results_and_cancel_does_not_export(isolated_store, monkeypatch):
    store = isolated_store
    records = [{"id": f"WOS:{i}", "title": f"Title {i}", "abstract": "A complete abstract",
                "authors": "", "year": "2024", "doi": "", "source": "ris", "language": "en",
                "doctype": "JOUR", "date": "2024", "external_id": f"WOS:{i}"} for i in range(4)]
    did = store.create_dataset("resume", [], records, {})
    config = {"criteria": {"domain": "test", "logic": "all", "criteria": [{"id": "T1", "question": "yes?"}]},
              "reviewers": [{"provider": "mock", "name": "reviewer_1", "role": "reviewer_1"}],
              "chunk_size": 1, "workers": 1}
    tid = store.create_task("resume", did, config)
    runner = TaskRunner(store)
    calls = []
    import litreview.batch as batch_module
    original = batch_module.BatchMockAgent.complete_json_with_usage
    def stop_after_first(self, system, user):
        calls.append(user)
        result = original(self, system, user)
        runner.cancel(tid)
        return result
    monkeypatch.setattr(batch_module.BatchMockAgent, "complete_json_with_usage", stop_after_first)
    runner.run(tid)
    assert store.get_task(tid)["status"] == "cancelled"
    assert len(calls) == 1
    assert store.get_results(tid) == []
    assert len(store.load_outputs(tid, "review", "reviewer_1")) == 1
    monkeypatch.setattr(batch_module.BatchMockAgent, "complete_json_with_usage", original)
    original_mock_call = batch_module.BatchMockAgent.complete_json_with_usage
    def count_remaining(self, system, user):
        calls.append(user)
        return original_mock_call(self, system, user)
    monkeypatch.setattr(batch_module.BatchMockAgent, "complete_json_with_usage", count_remaining)
    runner.start(tid)
    for thread in list(runner.threads.values()):
        thread.join(timeout=5)
    assert store.get_task(tid)["status"] == "completed"
    assert len(store.get_results(tid)) == 4
    assert len(calls) == 4
    saved = store.get_results(tid)
    store.update_task(tid, status="interrupted", phase="reviewing")
    def must_not_call(self, system, user):
        raise AssertionError("已完成评审不应再次调用模型")
    monkeypatch.setattr(batch_module.BatchMockAgent, "complete_json_with_usage", must_not_call)
    runner2 = TaskRunner(store)
    runner2.recover()
    for thread in list(runner2.threads.values()):
        thread.join(timeout=5)
    assert store.get_task(tid)["status"] == "completed"
    assert store.get_results(tid) == saved


    with TestClient(app) as client:
        assert client.get("/api/health").json() == {"ok": True}


def test_resume_only_arbitration_preserves_reviews_and_merges_results(isolated_store):
    store = isolated_store
    records, traces = [], {}
    for i, path in enumerate(("consistent", "arbitration_error")):
        rid = f"WOS:{i}"
        record = {"id": rid, "title": f"Paper {i}", "abstract": "abstract", "authors": "", "year": "2024",
                  "doi": "", "source": "ris", "language": "en", "doctype": "JOUR", "date": "2024", "external_id": rid}
        records.append(record)
        reviews = {f"reviewer_{n}": {"overall": n == 1 if path == "arbitration_error" else True,
                                   "answers": {"T1": True}, "reasonings": {"T1": "original reason"}}
                   for n in (1, 2)}
        traces[rid] = {"record": record, "criteria": ["T1"], "reviews": reviews, "path": path,
                       "final_overall": True if path == "consistent" else None,
                       "final_answers": {"T1": True} if path == "consistent" else {},
                       "human_review": path != "consistent"}
    did = store.create_dataset("resume-arb", [], records, {})
    cfg = {"criteria": {"domain": "test", "logic": "all", "criteria": [{"id": "T1", "question": "yes?"}]},
           "reviewers": [{"provider": "mock", "name": "reviewer_1", "role": "reviewer_1"},
                         {"provider": "mock", "name": "reviewer_2", "role": "reviewer_2"}],
           "arbiter": {"provider": "mock", "name": "arbiter", "role": "arbiter", "model": "Kimi-K3.1-Pro"},
           "chunk_size": 20, "workers": 1}
    tid = store.create_task("resume-arb", did, cfg)
    store.save_results(tid, traces)
    original = dict(traces["WOS:0"])
    runner = TaskRunner(store)
    runner.resume_arbitration(tid, {**cfg["arbiter"], "temperature": 1})
    assert store.get_task(tid)["status"] == "completed"
    unchanged = next(t for t in store.get_results(tid) if t["record_id"] == "WOS:0")
    assert unchanged["path"] == "consistent" and unchanged["reviews"] == original["reviews"]
    recovered = next(t for t in store.get_results(tid) if t["record_id"] == "WOS:1")
    assert recovered["path"] == "arbitrated" and recovered["final_overall"] is True
    assert recovered["reviews"]["reviewer_1"]["reasonings"]["T1"] == "original reason"
    assert store.get_recoveries(tid)[0]["config"]["temperature"] == 1
