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

    def start(self, tid: str):
        with self.lock:
            if tid in self.threads and self.threads[tid].is_alive():
                self.queued.add(tid)
                self.cancelled.add(tid)
                return
            self.queued.discard(tid)
            self.cancelled.discard(tid)
            thread = threading.Thread(target=self._run_safe, args=(tid,), daemon=True, name=f"screen-{tid}")
            self.threads[tid] = thread
            thread.start()

    def cancel(self, tid: str):
        self.cancelled.add(tid)
        self.store.update_task(tid, status="cancelling")

    def recover(self):
        for task in self.store.list_tasks():
            if task["status"] in {"pending", "running", "cancelling", "interrupted"}:
                self.store.clear_results(task["id"])
                self.store.update_task(task["id"], status="pending", phase="pending", error="")
                self.start(task["id"])

    def _run_safe(self, tid: str):
        try:
            self.run(tid)
        except Exception as e:
            self.store.update_task(tid, status="failed", error=str(e))
        finally:
            with self.lock:
                self.threads.pop(tid, None)
                queued = tid in self.queued
            if queued:
                self.start(tid)

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
