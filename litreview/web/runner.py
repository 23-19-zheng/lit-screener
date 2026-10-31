# -*- coding: utf-8 -*-
"""单进程后台任务执行；SQLite 保证分块完成即可恢复。"""
from __future__ import annotations

import threading
from datetime import datetime

from ..batch import BatchScreener, criteria_from_dict
from ..knowledge import KnowledgeRetriever, parse_entries
from ..pipeline import apply_filters
from ..records import Record
from .store import Store, now


class TaskRunner:
    def __init__(self, store: Store):
        self.store = store
        self.threads: dict[str, threading.Thread] = {}
        self.cancelled: set[str] = set()
        self.queued: set[str] = set()
        self.lock = threading.Lock()

    def start(self, tid: str, resume_arbitration: bool = False, arbiter_override: dict | None = None):
        with self.lock:
            if tid in self.threads and self.threads[tid].is_alive():
                self.queued.add(tid)
                self.cancelled.add(tid)
                return
            self.queued.discard(tid)
            self.cancelled.discard(tid)
            thread = threading.Thread(target=self._run_safe, args=(tid, resume_arbitration, arbiter_override),
                                      daemon=True, name=f"screen-{tid}")
            self.threads[tid] = thread
            thread.start()

    def cancel(self, tid: str):
        self.cancelled.add(tid)
        self.store.update_task(tid, status="cancelling")

    def recover(self):
        for task in self.store.list_tasks():
            if task["status"] not in {"pending", "running", "cancelling", "interrupted"}:
                continue
            # 已有最终结果时不能直接清空；补仲裁任务也只能恢复仲裁阶段。
            has_results = bool(self.store.get_results(task["id"]))
            if task["metrics"].get("resume_arbitration_only"):
                if has_results:
                    self.store.update_task(task["id"], status="pending", phase="arbitration_pending", error="")
                    self.start(task["id"], resume_arbitration=True,
                               arbiter_override=task["config"].get("arbiter"))
                else:
                    self.store.update_task(task["id"], status="interrupted", phase="recovery_required",
                                           error="补仲裁任务的结果列表缺失，请先从已保存分块恢复，不能自动重跑主评审。")
                continue
            self.store.update_task(task["id"], status="pending", phase="pending", error="")
            self.start(task["id"])

    def _run_safe(self, tid: str, resume_arbitration: bool = False, arbiter_override: dict | None = None):
        try:
            if resume_arbitration:
                self.resume_arbitration(tid, arbiter_override)
            else:
                self.run(tid)
        except Exception as e:
            self.store.update_task(tid, status="failed", error=str(e))
        finally:
            with self.lock:
                self.threads.pop(tid, None)
                queued = tid in self.queued
            if queued:
                self.start(tid)

    def resume_arbitration(self, tid: str, arbiter_override: dict | None = None):
        """只补仲裁失败文献，不创建任何主评审调用，也不删除其他结果。"""
        from ..batch import criteria_from_dict, make_chunks, make_batch_agent, parse_batch
        from ..knowledge import KnowledgeRetriever, parse_entries
        from ..records import Record

        task = self.store.get_task(tid)
        traces = {t["record_id"]: t for t in self.store.get_results(tid)}
        targets = [t for t in traces.values() if t.get("path") == "arbitration_error"]
        if not targets:
            self.store.update_task(tid, status="completed", phase="completed")
            return
        config = task["config"]
        arbiter = arbiter_override or config.get("arbiter")
        arbiter = {**arbiter, "timeout": arbiter.get("recovery_timeout", 90),
                   "retry_delays": arbiter.get("recovery_retry_delays", [3]),
                   "recovery_stream": True}
        if not arbiter:
            raise ValueError("该任务未配置仲裁模型")
        history_id = self.store.add_recovery(
            tid, "arbitration_only", arbiter, [t["record_id"] for t in targets], "running",
            {"previous_errors": [{"record_id": t["record_id"], "path": t["path"]} for t in targets]})
        chunk_reviewer = f"arbiter_recovery_{history_id}"
        self.store.update_task(tid, status="running", phase="arbitrating", error="", total=0, progress=0,
                               config={**config, "arbiter": arbiter})
        try:
            records = [Record(**t["record"]) for t in targets]
            saved_reviews = {spec["name"]: {t["record_id"]: t["reviews"][spec["name"]]
                                            for t in targets if t.get("reviews", {}).get(spec["name"])}
                             for spec in config["reviewers"]}
            pack, criteria = criteria_from_dict(config["criteria"])
            entries = parse_entries(task["knowledge"])
            retriever = KnowledgeRetriever(entries, config.get("knowledge_top_k", 4)) if entries else None
            screener = BatchScreener(
                pack=pack, criteria=criteria, reviewers=[], arbiter=arbiter,
                logic=config["criteria"].get("logic", "all"),
                chunk_size=1, char_budget=config.get("char_budget", 60000),
                workers=min(4, config.get("workers", 4)), retriever=retriever,
                saved_reviews=saved_reviews, saved_arbitrations={},
                should_stop=lambda: tid in self.cancelled)
            chunks = [[record] for record in records]
            screener._arb_chunks = chunks
            self.store.update_task(tid, total=len(targets))
            agent = make_batch_agent(arbiter)
            lock = threading.Lock()

            def work(job):
                index, chunk = job
                record = chunk[0]
                if tid in self.cancelled:
                    return {}
                try:
                    system, prompt = screener._prompt("arbitration", chunk, saved_reviews)
                    if hasattr(agent, "complete_json_stream"):
                        data, usage = agent.complete_json_stream(system, prompt)
                    else:
                        data, usage = agent.complete_json_with_usage(system, prompt)
                    outputs = parse_batch(data, chunk, criteria, screener.logic)
                    raw = {str(item.get("record_id") or item.get("id")): item for item in data["results"]}
                    for rid, output in outputs.items():
                        output["raw"] = raw[rid]
                    result = {"status": "done", "records": [record.id], "outputs": outputs, "usage": usage}
                except Exception as e:
                    result = {"status": "failed", "records": [record.id], "outputs": {record.id: {
                        "answers": {}, "reasonings": {}, "overall": None, "error": str(e), "raw": None}},
                        "usage": {}, "error": str(e)}
                with lock:
                    self.store.save_chunk(tid, "arbitration", chunk_reviewer, index, result["status"],
                                          result["records"], result["outputs"], result["usage"], result.get("error", ""))
                    # 单篇立即合并，后续失败不影响已成功的仲裁。
                    for rid, out in result["outputs"].items():
                        knowledge = screener.knowledge_cache.get(rid, traces[rid].get("knowledge_used", ""))
                        self.store.update_result_traces(tid, {rid: {
                            "arbitration": out, "final_answers": out["answers"], "final_overall": out["overall"],
                            "path": "arbitrated" if out["overall"] is not None else "arbitration_error",
                            "human_review": out["overall"] is None,
                            "review_reason": "评审分歧，已仲裁" if out["overall"] is not None else "仲裁失败/无法判定",
                            "knowledge_used": knowledge}})
                    done = len([c for c in self.store.get_chunks(tid, include_outputs=False)
                                if c["reviewer"] == chunk_reviewer and c["status"] == "done"])
                    self.store.update_task(tid, progress=done, metrics=self.store.usage(tid))
                return result["outputs"]

            from concurrent.futures import ThreadPoolExecutor
            recovered = {}
            with ThreadPoolExecutor(max_workers=screener.workers) as pool:
                for outputs in pool.map(work, list(enumerate(chunks))):
                    recovered.update(outputs)
            if tid in self.cancelled:
                self.store.update_recovery(history_id, "cancelled", {"recovered": len(recovered)})
                self.store.update_task(tid, status="cancelled", phase="cancelled")
                return
            changes = {}
            for rid, out in recovered.items():
                knowledge = screener.knowledge_cache.get(rid, traces[rid].get("knowledge_used", ""))
                changes[rid] = {"arbitration": out, "final_answers": out["answers"],
                                "final_overall": out["overall"],
                                "path": "arbitrated" if out["overall"] is not None else "arbitration_error",
                                "human_review": out["overall"] is None,
                                "review_reason": "评审分歧，已仲裁" if out["overall"] is not None else "仲裁解析失败/无法判定",
                                "knowledge_used": knowledge}
            self.store.update_result_traces(tid, changes)
            final = self.store.get_results(tid)
            metrics = self.store.usage(tid)
            metrics.update({
                "total": len(final),
                "include": sum(t.get("final_overall") is True for t in final),
                "exclude": sum(t.get("final_overall") is False for t in final),
                "undetermined": sum(t.get("final_overall") is None for t in final),
                "arbitrated": sum(t.get("path") == "arbitrated" for t in final),
                "human_review": sum(bool(t.get("human_review")) for t in final),
                "completed_at": now(),
            })
            failed = sum(t.get("path") == "arbitration_error" for t in final if t["record_id"] in traces)
            self.store.update_recovery(history_id, "completed" if not failed else "partial",
                                       {"recovered": len(recovered) - failed, "failed": failed})
            self.store.update_task(tid, status="completed", phase="completed", progress=1, total=1, metrics=metrics)
        except Exception as e:
            self.store.update_recovery(history_id, "failed", {"error": str(e)})
            raise

    def run(self, tid: str):
        task = self.store.get_task(tid)
        if not task:
            return
        if tid in self.cancelled:
            self.store.update_task(tid, status="cancelled", phase="cancelled")
            return
        dataset = self.store.get_dataset(task["dataset_id"])
        records = [Record(**r) for r in dataset["records"]]
        cfg = task["config"]
        if cfg.get("filters"):
            records, _, _ = apply_filters(records, cfg["filters"])
        if cfg.get("require_abstract", True):
            records = [r for r in records if r.abstract.strip()]
        limit = int(cfg.get("limit") or 0)
        if limit > 0:
            records = records[:limit]
        if not records:
            raise ValueError("过滤后没有可筛选的文献")
        pack, criteria = criteria_from_dict(cfg["criteria"])
        entries = parse_entries(task["knowledge"])
        retriever = KnowledgeRetriever(entries, cfg.get("knowledge_top_k", 4)) if entries else None
        self.store.update_task(tid, status="running", phase="reviewing", error="")
        screener = BatchScreener(
            pack=pack, criteria=criteria, reviewers=cfg["reviewers"], arbiter=cfg.get("arbiter"),
            logic=cfg["criteria"].get("logic", "all"), chunk_size=cfg.get("chunk_size", 20),
            char_budget=cfg.get("char_budget", 60000), workers=cfg.get("workers", 8),
            retriever=retriever, completed=self.store.completed_chunks(tid),
            saved_reviews={spec["name"]: self.store.load_outputs(tid, "review", spec["name"])
                           for spec in cfg["reviewers"]},
            saved_arbitrations=self.store.load_outputs(tid, "arbitration", "arbiter"),
            should_stop=lambda: tid in self.cancelled)
        progress_lock = threading.Lock()

        def on_phase(phase, _, total):
            if phase == "arbitrating":
                done = self.store.chunk_stats(tid).get("arbitration:done", {}).get("count", 0)
                self.store.update_task(tid, phase=phase, total=total, progress=done)

        def on_result(kind, reviewer, index, result):
            if not result:
                return
            with progress_lock:
                self.store.save_chunk(tid, kind, reviewer, index, result["status"],
                                      result.get("records", []), result.get("outputs", {}),
                                      result.get("usage", {}), result.get("error", ""))
                stats = self.store.chunk_stats(tid)
                done = stats.get(f"{kind}:done", {}).get("count", 0)
                total = total_review_chunks if kind == "review" else len(screener._arb_chunks)
                self.store.update_task(tid, progress=done, total=total, metrics=self.store.usage(tid))

        screener.on_phase, screener.on_result = on_phase, on_result
        from ..batch import make_chunks
        chunks = make_chunks(records, screener.chunk_size, screener.char_budget)
        total_review_chunks = len(chunks) * len(screener.reviewers)
        self._arb_chunks = []
        self.store.update_task(tid, total=total_review_chunks,
                               progress=len([c for c in self.store.get_chunks(tid)
                                             if c["kind"] == "review" and c["status"] == "done"]))
        traces = screener.run(records)
        if tid in self.cancelled:
            self.store.update_task(tid, status="cancelled", phase="cancelled")
            return
        records_by_id = {r.id: r for r in records}
        persisted = {}
        for rid, trace in traces.items():
            trace["record"] = records_by_id[rid].to_dict()
            trace["criteria"] = [c.id for c in criteria]
            persisted[rid] = trace
        self.store.clear_results(tid)
        self.store.save_results(tid, persisted)
        metrics = self.store.usage(tid)
        metrics.update({
            "total": len(persisted),
            "include": sum(t.get("final_overall") is True for t in persisted.values()),
            "exclude": sum(t.get("final_overall") is False for t in persisted.values()),
            "undetermined": sum(t.get("final_overall") is None for t in persisted.values()),
            "arbitrated": sum(t.get("path") == "arbitrated" for t in persisted.values()),
            "human_review": sum(bool(t.get("human_review")) for t in persisted.values()),
            "completed_at": now(),
            "duration_seconds": round((datetime.fromisoformat(now()) -
                                       datetime.fromisoformat(task["created_at"])).total_seconds(), 2),
        })
        self.store.update_task(tid, status="completed", phase="completed",
                               progress=1, total=1, metrics=metrics)
