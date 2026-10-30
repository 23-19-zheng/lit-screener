# -*- coding: utf-8 -*-
"""本地运行数据：上传文件、不可变配置、分块结果与任务状态。"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VAR = Path(os.environ.get("LITREVIEW_VAR", ROOT / "var"))
UPLOADS = VAR / "uploads"
DB = VAR / "litreview.db"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class Store:
    def __init__(self, path: Path = DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS datasets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, files TEXT NOT NULL,
                    records TEXT NOT NULL, stats TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, dataset_id TEXT NOT NULL,
                    config TEXT NOT NULL, knowledge TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL, phase TEXT NOT NULL DEFAULT 'pending',
                    progress INTEGER NOT NULL DEFAULT 0, total INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '', metrics TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chunks (
                    task_id TEXT NOT NULL, kind TEXT NOT NULL, reviewer TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL, status TEXT NOT NULL,
                    record_ids TEXT NOT NULL, outputs TEXT NOT NULL DEFAULT '{}',
                    usage TEXT NOT NULL DEFAULT '{}', error TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (task_id, kind, reviewer, chunk_index));
                CREATE TABLE IF NOT EXISTS results (
                    task_id TEXT NOT NULL, record_id TEXT NOT NULL,
                    trace TEXT NOT NULL, PRIMARY KEY (task_id, record_id));
                CREATE TABLE IF NOT EXISTS criteria_presets (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, content TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS drafts (
                    id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL,
                    dataset_id TEXT NOT NULL, config TEXT NOT NULL, knowledge TEXT NOT NULL,
                    updated_at TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False)

    def create_dataset(self, name: str, files: list[str], records: list[dict], stats: dict) -> str:
        did = new_id("data")
        with self.connect() as db:
            db.execute("INSERT INTO datasets VALUES (?,?,?,?,?,?)",
                       (did, name, self._json(files), self._json(records), self._json(stats), now()))
        return did

    def get_dataset(self, did: str, include_records: bool = True) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM datasets WHERE id=?", (did,)).fetchone()
        if not row:
            return None
        data = dict(row)
        for key in ("files", "stats"):
            data[key] = json.loads(data[key])
        data["records"] = json.loads(data["records"]) if include_records else []
        return data

    def list_datasets(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,name,files,stats,created_at FROM datasets ORDER BY created_at DESC").fetchall()
        return [{**dict(r), "files": json.loads(r["files"]), "stats": json.loads(r["stats"])} for r in rows]

    def create_task(self, name: str, dataset_id: str, config: dict, knowledge: str = "") -> str:
        tid = new_id("run")
        with self.connect() as db:
            db.execute("INSERT INTO tasks(id,name,dataset_id,config,knowledge,status,created_at,updated_at) VALUES(?,?,?,?,?,'pending',?,?)",
                       (tid, name, dataset_id, self._json(config), knowledge, now(), now()))
        return tid

    def get_task(self, tid: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()
        if not row:
            return None
        task = dict(row)
        task["config"] = json.loads(task["config"])
        task["metrics"] = json.loads(task["metrics"])
        return task

    def list_tasks(self) -> list[dict]:
        with self.connect() as db:
            ids = [r[0] for r in db.execute("SELECT id FROM tasks ORDER BY created_at DESC").fetchall()]
        return [self.get_task(tid) for tid in ids]

    def update_task(self, tid: str, **fields):
        allowed = {"status", "phase", "progress", "total", "error", "metrics", "name"}
        values = []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"不可更新字段 {key}")
            values.append(self._json(value) if key == "metrics" else value)
        values += [now(), tid]
        with self.connect() as db:
            db.execute(f"UPDATE tasks SET {','.join(f'{k}=?' for k in fields)},updated_at=? WHERE id=?", values)

    def save_chunk(self, tid: str, kind: str, reviewer: str, index: int,
                   status: str, record_ids: list[str], outputs: dict, usage: dict, error: str = ""):
        with self.lock, self.connect() as db:
            db.execute("""INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id,kind,reviewer,chunk_index) DO UPDATE SET
                status=excluded.status,record_ids=excluded.record_ids,outputs=excluded.outputs,
                usage=excluded.usage,error=excluded.error,updated_at=excluded.updated_at""",
                (tid, kind, reviewer, index, status, self._json(record_ids), self._json(outputs),
                 self._json(usage), error, now()))

    def get_chunks(self, tid: str, include_outputs: bool = True) -> list[dict]:
        columns = "*" if include_outputs else "task_id,kind,reviewer,chunk_index,status,usage,error,updated_at"
        with self.connect() as db:
            rows = db.execute(f"SELECT {columns} FROM chunks WHERE task_id=?", (tid,)).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            for key in (("record_ids", "outputs", "usage") if include_outputs else ("usage",)):
                item[key] = json.loads(item[key])
            out.append(item)
        return out

    def chunk_stats(self, tid: str) -> dict[str, dict[str, int]]:
        with self.connect() as db:
            rows = db.execute("""SELECT kind,status,COUNT(*) AS count,
                COALESCE(SUM(CAST(json_extract(usage,'$.input_tokens') AS INTEGER)),0) AS input_tokens,
                COALESCE(SUM(CAST(json_extract(usage,'$.output_tokens') AS INTEGER)),0) AS output_tokens
                FROM chunks WHERE task_id=? GROUP BY kind,status""", (tid,)).fetchall()
        return {f"{r['kind']}:{r['status']}": dict(r) for r in rows}

    def completed_chunks(self, tid: str) -> set[tuple[str, str, int]]:
        return {(c["kind"], c["reviewer"], c["chunk_index"])
                for c in self.get_chunks(tid) if c["status"] == "done"}

    def load_outputs(self, tid: str, kind: str, reviewer: str) -> dict[str, dict]:
        outputs = {}
        for c in self.get_chunks(tid):
            if c["kind"] == kind and c["reviewer"] == reviewer and c["status"] == "done":
                outputs.update(c["outputs"])
        return outputs

    def usage(self, tid: str) -> dict:
        usage = {"input_tokens": 0, "output_tokens": 0, "requests": 0, "failed_requests": 0}
        for stats in self.chunk_stats(tid).values():
            if stats["status"] == "done":
                usage["requests"] += stats["count"]
                usage["input_tokens"] += stats["input_tokens"]
                usage["output_tokens"] += stats["output_tokens"]
            elif stats["status"] == "failed":
                usage["failed_requests"] += stats["count"]
        return usage

    def save_results(self, tid: str, results: dict[str, dict]):
        with self.lock, self.connect() as db:
            db.execute("DELETE FROM results WHERE task_id=?", (tid,))
            db.executemany("INSERT OR REPLACE INTO results VALUES (?,?,?)",
                           [(tid, rid, self._json(trace)) for rid, trace in results.items()])

    def get_results(self, tid: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT record_id,trace FROM results WHERE task_id=?", (tid,)).fetchall()
        return [{"record_id": r["record_id"], **json.loads(r["trace"])} for r in rows]

    def clear_results(self, tid: str):
        with self.connect() as db:
            db.execute("DELETE FROM results WHERE task_id=?", (tid,))

    def reset_failed_chunks(self, tid: str):
        with self.connect() as db:
            db.execute("DELETE FROM chunks WHERE task_id=? AND status!='done'", (tid,))
            db.execute("DELETE FROM results WHERE task_id=?", (tid,))

    def save_draft(self, name: str, dataset_id: str, config: dict, knowledge: str):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO drafts VALUES (1,?,?,?,?,?)",
                       (name, dataset_id, self._json(config), knowledge, now()))

    def get_draft(self) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM drafts WHERE id=1").fetchone()
        if not row:
            return None
        data = dict(row)
        data["config"] = json.loads(data["config"])
        return data

    def save_preset(self, name: str, content: dict, preset_id: str | None = None) -> str:
        pid = preset_id or new_id("preset")
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO criteria_presets VALUES (?,?,?,?)",
                       (pid, name, self._json(content), now()))
        return pid

    def list_presets(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM criteria_presets ORDER BY updated_at DESC").fetchall()
        return [{**dict(r), "content": json.loads(r["content"])} for r in rows]

    def delete_preset(self, pid: str):
        with self.connect() as db:
            db.execute("DELETE FROM criteria_presets WHERE id=?", (pid,))
