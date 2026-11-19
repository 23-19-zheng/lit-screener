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
    monkeypatch.setattr(web_module, "UPLOADS", tmp_path / "uploads")  # 不写入真实 var/uploads
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


def _mock_task(store, status):
    records = [{"id": "WOS:1", "title": "T", "abstract": "A", "authors": "", "year": "2024", "doi": "",
                "source": "ris", "language": "en", "doctype": "JOUR", "date": "2024", "external_id": "WOS:1"}]
    did = store.create_dataset("cancel", [], records, {})
    cfg = {"criteria": {"domain": "test", "logic": "all", "criteria": [{"id": "T1", "question": "yes?"}]},
           "reviewers": [{"provider": "mock", "model": "m", "name": "reviewer_1", "role": "reviewer_1"}],
           "chunk_size": 1, "workers": 1}
    tid = store.create_task("cancel", did, cfg)
    store.update_task(tid, status=status)
    return tid


def test_cancel_task_without_thread_finishes_and_can_retry(isolated_store):
    with TestClient(app) as client:
        tid = _mock_task(isolated_store, "interrupted")  # 服务启动后才中断，没有线程接手
        assert client.post(f"/api/tasks/{tid}/cancel").json()["status"] == "cancelled"
        assert client.post(f"/api/tasks/{tid}/retry").status_code == 200
        assert wait(client, tid)["status"] == "completed"


def test_recover_does_not_restart_cancelling_task(isolated_store):
    tid = _mock_task(isolated_store, "cancelling")
    runner = TaskRunner(isolated_store)
    runner.recover()
    assert not runner.threads
    assert isolated_store.get_task(tid)["status"] == "cancelled"


def test_create_task_rejects_blank_criterion_question(isolated_store):
    tid = _mock_task(isolated_store, "completed")
    task = isolated_store.get_task(tid)
    cfg = {**task["config"], "criteria": {"logic": "all", "criteria": [{"id": "T1", "question": "  "}]}}
    with TestClient(app) as client:
        res = client.post("/api/tasks", json={"name": "x", "dataset_id": task["dataset_id"], "config": cfg})
        assert res.status_code == 400


def test_resume_arbitration_progress_keeps_resume_only_flag(isolated_store, monkeypatch):
    store = isolated_store
    tid = _mock_task(store, "pending")
    record = store.get_dataset(store.get_task(tid)["dataset_id"])["records"][0]
    reviews = {f"reviewer_{n}": {"overall": n == 1, "answers": {"T1": n == 1}, "reasonings": {}} for n in (1, 2)}
    store.save_results(tid, {"WOS:1": {"record": record, "criteria": ["T1"], "reviews": reviews,
                                       "path": "arbitration_error", "final_overall": None,
                                       "final_answers": {}, "human_review": True}})
    cfg = store.get_task(tid)["config"]
    cfg["reviewers"].append({"provider": "mock", "name": "reviewer_2", "role": "reviewer_2"})
    cfg["arbiter"] = {"provider": "mock", "name": "arbiter", "role": "arbiter", "model": "m"}
    store.update_task(tid, config=cfg, metrics={"resume_arbitration_only": True})
    flags = []
    original = store.update_task
    def spy(t, **fields):
        original(t, **fields)
        if "progress" in fields and fields.get("status") != "completed":
            flags.append(store.get_task(t)["metrics"].get("resume_arbitration_only"))
    monkeypatch.setattr(store, "update_task", spy)
    TaskRunner(store).resume_arbitration(tid)
    assert flags and all(flags)


def test_status_endpoint_is_lightweight(isolated_store, monkeypatch):
    tid = _mock_task(isolated_store, "completed")
    with TestClient(app) as client:
        monkeypatch.setattr(isolated_store, "get_results", lambda *a: pytest.fail("轮询不应读取全部结果"))
        isolated_store.update_task(tid, status="running", phase="reviewing", progress=3, total=7)
        body = client.get(f"/api/tasks/{tid}/status").json()
    assert body == {"id": tid, "status": "running", "phase": "reviewing", "progress": 3, "total": 7, "error": ""}


def test_upload_parsing_does_not_block_event_loop(isolated_store, monkeypatch):
    import threading
    started, release = threading.Event(), threading.Event()
    def slow_load(path):
        started.set()
        release.wait(5)
        return []
    monkeypatch.setattr(web_module, "load_records", slow_load)
    with TestClient(app) as client:
        t = threading.Thread(target=lambda: client.post("/api/datasets", files=[("files", ("a.ris", "x", "text/plain"))]))
        t.start()
        assert started.wait(5)
        health = {}
        h = threading.Thread(target=lambda: health.update(r=client.get("/api/health")))
        h.start()
        h.join(2)
        release.set()
        t.join(5)
        assert "r" in health, "解析上传文件时整个服务被阻塞"


def test_upload_does_not_keep_raw_files(isolated_store, tmp_path, monkeypatch):
    monkeypatch.setattr(web_module, "UPLOADS", tmp_path / "uploads")
    ris = "TY  - JOUR\nTI  - A\nAB  - B\nPY  - 2025\nER  -\n"
    with TestClient(app) as client:
        assert client.post("/api/datasets", files=[("files", ("a.ris", ris, "text/plain"))]).status_code == 200
        assert client.post("/api/datasets", files=[("files", ("b.ris", "garbage", "text/plain"))]).status_code == 400
    assert not any((tmp_path / "uploads").rglob("*.*"))  # 解析完即删除，数据已在数据库


def test_delete_task_removes_all_rows(isolated_store):
    tid = _mock_task(isolated_store, "completed")
    isolated_store.save_chunk(tid, "review", "reviewer_1", 0, "done", ["WOS:1"], {}, {})
    isolated_store.save_results(tid, {"WOS:1": {"path": "consistent"}})
    isolated_store.add_recovery(tid, "arbitration_only", {}, [], "completed", {})
    with TestClient(app) as client:
        assert client.delete(f"/api/tasks/{tid}").status_code == 200
        assert client.get(f"/api/tasks/{tid}").status_code == 404
    assert not isolated_store.get_chunks(tid) and not isolated_store.get_results(tid)
    assert not isolated_store.get_recoveries(tid)


def test_delete_running_task_is_rejected(isolated_store):
    with TestClient(app) as client:
        tid = _mock_task(isolated_store, "running")
        assert client.delete(f"/api/tasks/{tid}").status_code == 409


def test_delete_dataset_only_when_unreferenced(isolated_store):
    tid = _mock_task(isolated_store, "completed")
    did = isolated_store.get_task(tid)["dataset_id"]
    with TestClient(app) as client:
        assert client.delete(f"/api/datasets/{did}").status_code == 409  # 任务克隆/重跑仍依赖它
        client.delete(f"/api/tasks/{tid}")
        assert client.delete(f"/api/datasets/{did}").status_code == 200
        assert client.get(f"/api/datasets/{did}").status_code == 404


def test_resume_arbitration_does_not_rescan_chunks_per_record(isolated_store, monkeypatch):
    store = isolated_store
    tid = _mock_task(store, "pending")
    base = store.get_dataset(store.get_task(tid)["dataset_id"])["records"][0]
    reviews = {f"reviewer_{n}": {"overall": n == 1, "answers": {"T1": n == 1}, "reasonings": {}} for n in (1, 2)}
    store.save_results(tid, {f"WOS:{i}": {"record": {**base, "id": f"WOS:{i}"}, "criteria": ["T1"],
                                          "reviews": reviews, "path": "arbitration_error",
                                          "final_overall": None, "final_answers": {}, "human_review": True}
                             for i in range(20)})
    cfg = store.get_task(tid)["config"]
    cfg["reviewers"].append({"provider": "mock", "name": "reviewer_2", "role": "reviewer_2"})
    cfg["arbiter"] = {"provider": "mock", "name": "arbiter", "role": "arbiter", "model": "m"}
    store.update_task(tid, config=cfg)
    scans = []
    for name in ("get_chunks", "usage"):
        real = getattr(store, name)
        monkeypatch.setattr(store, name, lambda *a, _r=real, _n=name, **k: scans.append(_n) or _r(*a, **k))
    TaskRunner(store).resume_arbitration(tid)
    assert store.get_task(tid)["status"] == "completed"
    assert len(scans) <= 4  # 与篇数无关，而不是每篇全表扫描一次


def test_themes_endpoint_lists_theme_packages(isolated_store):
    with TestClient(app) as client:
        themes = client.get("/api/themes").json()
    anammox = next(t for t in themes if t["id"] == "anammox")
    assert "_template" not in {t["id"] for t in themes}
    assert [c["id"] for c in anammox["criteria"]["criteria"]] == ["A1", "A2", "A3", "A4", "A5"]
    assert anammox["criteria"]["logic"] == "all" and anammox["criteria"]["domain"]
    assert "## " in anammox["knowledge"]
    assert anammox["filters"]["language"] == "en"


def test_defaults_come_from_config_not_hardcoded(isolated_store, monkeypatch, tmp_path):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("criteria:\n  pack: themes/anammox/criteria.yaml\n  inclusion_logic: any\n"
                   "agents:\n  reviewer_1:\n    provider: openai_compatible\n    model: my-model\n"
                   "    base_url: http://x\n    api_key_env: MY_KEY\n", encoding="utf-8")
    monkeypatch.setattr(web_module, "DEFAULT_CONFIG", cfg)
    with TestClient(app) as client:
        d = client.get("/api/defaults").json()
    assert d["criteria"]["criteria"][0]["id"] == "A1" and d["criteria"]["logic"] == "any"
    assert d["default_model"]["model"] == "my-model" and d["default_model"]["api_key_env"] == "MY_KEY"


def test_arbitration_retry_uses_configured_temperature(isolated_store, monkeypatch):
    tid = _mock_task(isolated_store, "completed")
    cfg = isolated_store.get_task(tid)["config"]
    cfg["arbiter"] = {"provider": "mock", "name": "arbiter", "model": "Kimi-K3.1-Pro", "temperature": 0.3}
    isolated_store.update_task(tid, config=cfg)
    isolated_store.save_results(tid, {"WOS:1": {"path": "arbitration_error"}})
    started = {}
    with TestClient(app) as client:
        monkeypatch.setattr(web_module.runner, "start", lambda t, **k: started.update(k))
        assert client.post(f"/api/tasks/{tid}/arbitration-retry").status_code == 200
    assert started["arbiter_override"]["temperature"] == 0.3  # 不再按模型名特判
