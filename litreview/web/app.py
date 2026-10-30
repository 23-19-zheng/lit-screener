# -*- coding: utf-8 -*-
"""本地单用户 Web API，默认仅绑定 127.0.0.1。"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import uuid
from collections import Counter
from pathlib import Path

import yaml
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..evaluate import evaluate
from ..records import assign_record_ids, dedupe, load_records
from .runner import TaskRunner
from .store import ROOT, Store, UPLOADS, VAR, new_id

load_dotenv(ROOT / ".env")
store = Store()
runner = TaskRunner(store)
app = FastAPI(title="Lit Screener", version="0.2.0")


class TaskRequest(BaseModel):
    name: str = "未命名筛选"
    dataset_id: str
    knowledge: str = ""
    config: dict


class PresetRequest(BaseModel):
    id: str | None = None
    name: str
    content: dict


class CompareRequest(BaseModel):
    task_ids: list[str] = Field(min_length=2, max_length=6)


@app.on_event("startup")
def startup():
    runner.recover()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/defaults")
def defaults():
    with open(ROOT / "criteria/rare_earth.yaml", encoding="utf-8") as f:
        criteria = yaml.safe_load(f)
    return {"criteria": criteria, "mock_available": True,
            "key_status": {"ARK_API_KEY": bool(os.environ.get("ARK_API_KEY"))},
            "default_model": {"provider": "openai_compatible", "model": "deepseek-v4.1-flash",
                              "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
                              "api_key_env": "ARK_API_KEY", "temperature": 0}}


@app.post("/api/datasets")
async def upload_dataset(files: list[UploadFile] = File(...)):
    if not files or len(files) > 30:
        raise HTTPException(400, "请选择 1–30 个同格式分卷")
    allowed = {".ris", ".txt", ".csv"}
    extensions = {Path(f.filename or "").suffix.lower() for f in files}
    if len(extensions) != 1 or not extensions <= allowed:
        raise HTTPException(400, "请一次上传同一格式的 RIS、TXT 或 CSV 文件，不要混传两种格式")
    upload_dir = UPLOADS / new_id("upload")
    upload_dir.mkdir(parents=True)
    records, names, total = [], [], 0
    try:
        for upload in files:
            name = Path(upload.filename or "records").name
            if not re.search(r"\.(ris|txt|csv)$", name, re.I):
                raise ValueError("不支持的文件扩展名")
            data = await upload.read(64 * 1024 * 1024 + 1)
            if len(data) > 64 * 1024 * 1024:
                raise ValueError(f"文件 {name} 超过 64MB 限制")
            total += len(data)
            if total > 200 * 1024 * 1024:
                raise ValueError("一次上传总大小不能超过 200MB")
            path = upload_dir / f"{uuid.uuid4().hex}{Path(name).suffix.lower()}"
            path.write_bytes(data)
            names.append(name)
            loaded = load_records(str(path))
            if not loaded:
                raise ValueError(f"文件 {name} 未解析到文献")
            records.extend(loaded)
        raw_count = len(records)
        records = assign_record_ids(dedupe(records))
        stats = {"raw": raw_count, "unique": len(records),
                 "missing_abstract": sum(not r.abstract.strip() for r in records),
                 "missing_doi": sum(not r.doi.strip() for r in records),
                 "years": dict(sorted(Counter(r.year or "未知" for r in records).items())),
                 "languages": dict(Counter(r.language or "未知" for r in records).most_common()),
                 "doctypes": dict(Counter(r.doctype or "未知" for r in records).most_common())}
        did = store.create_dataset("、".join(names), names, [r.to_dict() for r in records], stats)
        return {"dataset": store.get_dataset(did, include_records=False),
                "preview": [r.to_dict() for r in records[:8]]}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/datasets")
def datasets():
    return store.list_datasets()


@app.get("/api/datasets/{did}")
def dataset(did: str, offset: int = 0, limit: int = 20):
    data = store.get_dataset(did)
    if not data:
        raise HTTPException(404, "数据集不存在")
    records = data.pop("records")
    return {**data, "preview": records[max(0, offset):max(0, offset) + min(limit, 100)]}


def _validate_task(payload: TaskRequest):
    if not store.get_dataset(payload.dataset_id, include_records=False):
        raise HTTPException(400, "请先选择有效数据集")
    cfg = payload.config
    try:
        from ..batch import criteria_from_dict
        criteria_from_dict(cfg.get("criteria") or {})
    except (KeyError, TypeError, ValueError) as e:
        raise HTTPException(400, f"筛选判据无效：{e}") from e
    reviewers = cfg.get("reviewers") or []
    if not 1 <= len(reviewers) <= 8:
        raise HTTPException(400, "评审员数量须在 1–8 之间")
    if len({r.get("name") for r in reviewers}) != len(reviewers):
        raise HTTPException(400, "评审员名称不能重复")
    for spec in reviewers + ([cfg.get("arbiter")] if cfg.get("arbiter") else []):
        if not spec.get("model") or not spec.get("provider"):
            raise HTTPException(400, "请完整配置评审模型")
        if spec["provider"] != "mock" and not os.environ.get(spec.get("api_key_env", "")):
            raise HTTPException(400, f"环境变量 {spec.get('api_key_env')} 未设置；Mock 模式无需密钥")
    if not 1 <= int(cfg.get("chunk_size", 20)) <= 100 or not 1 <= int(cfg.get("workers", 8)) <= 32:
        raise HTTPException(400, "分块大小须为 1–100，线程数须为 1–32")
    cfg["criteria"]["logic"] = cfg["criteria"].get("logic", "all")
    if cfg["criteria"]["logic"] not in {"all", "any"}:
        raise HTTPException(400, "判据组合只支持 all/any")


@app.post("/api/tasks", status_code=201)
def create_task(payload: TaskRequest):
    _validate_task(payload)
    tid = store.create_task(payload.name.strip() or "未命名筛选", payload.dataset_id,
                            payload.config, payload.knowledge)
    runner.start(tid)
    return store.get_task(tid)


@app.get("/api/tasks")
def tasks():
    return store.list_tasks()


@app.get("/api/tasks/{tid}")
def task(tid: str):
    task = store.get_task(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    task["usage"] = store.usage(tid)
    task["chunks"] = store.get_chunks(tid, include_outputs=False)
    return task


@app.post("/api/tasks/{tid}/cancel")
def cancel(tid: str):
    task = store.get_task(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] in {"running", "pending", "cancelling", "interrupted"}:
        runner.cancel(tid)
    return store.get_task(tid)


@app.post("/api/tasks/{tid}/retry")
def retry(tid: str):
    task = store.get_task(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    if task["status"] in {"running", "pending", "cancelling"}:
        raise HTTPException(409, "任务正在运行，请先取消")
    store.reset_failed_chunks(tid)
    store.update_task(tid, status="pending", phase="pending", progress=0, total=0, error="")
    runner.start(tid)
    return store.get_task(tid)


@app.post("/api/tasks/{tid}/clone")
def clone(tid: str):
    task = store.get_task(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    return {"name": task["name"] + "（副本）", "dataset_id": task["dataset_id"],
            "knowledge": task["knowledge"], "config": task["config"]}


@app.get("/api/tasks/{tid}/results")
def results(tid: str, decision: str = "", q: str = "", offset: int = 0, limit: int = 50):
    if not store.get_task(tid):
        raise HTTPException(404, "任务不存在")
    traces = store.get_results(tid)
    query = q.strip().lower()
    filtered = [t for t in traces if
                (not decision or {True: "include", False: "exclude", None: "undetermined"}[t.get("final_overall")] == decision)
                and (not query or query in (t["record"].get("title", "") + t["record"].get("doi", "")).lower())]
    return {"total": len(filtered), "items": filtered[max(0, offset):max(0, offset) + min(limit, 200)]}


def _csv_safe(value) -> str:
    text = str(value if value is not None else "")
    return "'" + text if text.startswith(("=", "+", "-", "@")) else text


@app.get("/api/tasks/{tid}/export/{kind}")
def export(tid: str, kind: str):
    task = store.get_task(tid)
    if not task:
        raise HTTPException(404, "任务不存在")
    traces = store.get_results(tid)
    if kind == "trace":
        content = "\n".join(json.dumps(t, ensure_ascii=False) for t in traces) + "\n"
        return StreamingResponse(iter([content.encode()]), media_type="application/x-ndjson",
                                 headers={"Content-Disposition": f'attachment; filename="{tid}_trace.jsonl"'})
    if kind not in {"include", "results", "review"}:
        raise HTTPException(404, "不支持的导出类型")
    ids = task["config"]["criteria"].get("criteria", [])
    ids = [c["id"] for c in ids]
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["record_id", "doi", "year", "title", "decision", "human_review", "path"] + ids)
    for t in traces:
        decision = {True: "include", False: "exclude", None: "undetermined"}[t.get("final_overall")]
        if kind == "include" and decision != "include":
            continue
        if kind == "review" and not t.get("human_review"):
            continue
        record = t["record"]
        writer.writerow([_csv_safe(v) for v in [t["record_id"], record.get("doi"), record.get("year"),
                         record.get("title"), decision, "Y" if t.get("human_review") else "", t.get("path")]] +
                        [t.get("final_answers", {}).get(i) for i in ids])
    return StreamingResponse(iter([output.getvalue().encode("utf-8-sig")]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{tid}_{kind}.csv"'})


@app.get("/api/compare")
def compare(ids: str):
    selected = [t for t in (store.get_task(i) for i in ids.split(",")[:6]) if t]
    if len(selected) < 2:
        raise HTTPException(400, "至少选择两个有效任务")
    response = []
    for task in selected:
        result = store.get_results(task["id"])
        votes = {t["record_id"]: t.get("final_overall") for t in result}
        response.append({"id": task["id"], "name": task["name"], "status": task["status"],
                         "reviewers": len(task["config"].get("reviewers") or []),
                         "models": [r.get("model") for r in task["config"].get("reviewers") or []],
                         "metrics": task["metrics"], "decisions": votes})
    overlap = set(response[0]["decisions"])
    for item in response[1:]:
        overlap &= set(item["decisions"])
    for item in response:
        item["decision_overlap"] = len(overlap)
        item.pop("decisions")
    if len(response) == 2 and overlap:
        a, b = response[0], response[1]
        # 分歧重合度只在同一数据集、相同记录集合上有意义。
        traces_a = {t["record_id"]: t.get("final_overall") for t in store.get_results(a["id"])}
        traces_b = {t["record_id"]: t.get("final_overall") for t in store.get_results(b["id"])}
        same = sum(traces_a[i] == traces_b[i] for i in overlap)
        response[0]["pair_agreement"] = round(same / len(overlap), 4)
    return response


@app.post("/api/tasks/{tid}/evaluate")
async def evaluate_task(tid: str, labels: UploadFile = File(...)):
    if not store.get_task(tid):
        raise HTTPException(404, "任务不存在")
    folder = VAR / "evaluation"
    folder.mkdir(parents=True, exist_ok=True)
    suffix = Path(labels.filename or "").suffix.lower()
    if suffix != ".csv":
        raise HTTPException(400, "金标准须为 CSV")
    label_path = folder / f"{tid}_{uuid.uuid4().hex}.csv"
    trace_path = folder / f"{tid}_{uuid.uuid4().hex}.jsonl"
    label_path.write_bytes(await labels.read(10 * 1024 * 1024))
    trace_path.write_text("\n".join(json.dumps(t, ensure_ascii=False) for t in store.get_results(tid)),
                          encoding="utf-8")
    try:
        return evaluate(str(trace_path), str(label_path))
    except (ValueError, OSError) as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/presets")
def presets():
    return store.list_presets()


@app.post("/api/presets")
def save_preset(payload: PresetRequest):
    pid = store.save_preset(payload.name, payload.content, payload.id)
    return {"id": pid}


@app.delete("/api/presets/{pid}")
def delete_preset(pid: str):
    store.delete_preset(pid)
    return {"ok": True}


@app.post("/api/presets/import")
async def import_preset(file: UploadFile = File(...)):
    try:
        content = yaml.safe_load((await file.read(2 * 1024 * 1024)).decode("utf-8-sig"))
        if not isinstance(content, dict) or not content.get("criteria"):
            raise ValueError("YAML 中没有 criteria")
        return content
    except (yaml.YAMLError, UnicodeDecodeError, ValueError) as e:
        raise HTTPException(400, f"判据 YAML 无法读取：{e}") from e


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="web")
