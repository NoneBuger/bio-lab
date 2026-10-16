"""FastAPI service for asynchronous QC jobs."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from celery.result import AsyncResult
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from .celery_app import celery_app
from .schemas import TaskStatus, TaskSubmitted
from .tasks import JOB_ROOT, run_qc_task


app = FastAPI(title="Bio Lab API", version="0.2.0")
MAX_UPLOAD_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(4 * 1024**3)))
ALLOWED_ARTIFACTS = {
    "qc_report",
    "qc_summary",
    "provenance",
    "qc_before",
    "qc_after",
    "qc_before_scatter",
    "qc_after_scatter",
    "assessment_report",
    "assessment_json",
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/qc", response_model=TaskSubmitted, status_code=202)
async def submit_qc(
    file: UploadFile = File(...),
    instruction: str = Form(default=""),
    min_genes: int = Form(default=200),
    min_cells: int = Form(default=3),
    max_mito_pct: float = Form(default=20.0),
) -> TaskSubmitted:
    if not file.filename or not file.filename.lower().endswith(".h5ad"):
        raise HTTPException(status_code=400, detail="Only .h5ad files are supported")
    if min_genes < 0 or min_cells < 1 or not 0 <= max_mito_pct <= 100:
        raise HTTPException(status_code=400, detail="Invalid QC parameters")

    task_id = str(uuid.uuid4())
    input_path = JOB_ROOT / task_id / "input" / "sample.h5ad"
    input_path.parent.mkdir(parents=True, exist_ok=True)
    total_bytes = 0
    with input_path.open("wb") as target:
        while chunk := await file.read(8 * 1024 * 1024):
            total_bytes += len(chunk)
            if total_bytes > MAX_UPLOAD_BYTES:
                input_path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Uploaded file is too large")
            target.write(chunk)

    run_qc_task.apply_async(
        args=[str(input_path)],
        kwargs={
            "instruction": instruction,
            "min_genes": min_genes,
            "min_cells": min_cells,
            "max_mito_pct": max_mito_pct,
        },
        task_id=task_id,
    )
    return TaskSubmitted(task_id=task_id)


@app.get("/api/v1/qc/{task_id}", response_model=TaskStatus)
def get_qc_status(task_id: str) -> TaskStatus:
    result = AsyncResult(task_id, app=celery_app)
    info = result.info if isinstance(result.info, dict) else {}
    if result.successful():
        return TaskStatus(task_id=task_id, status="SUCCESS", progress=100, result=result.result)
    if result.failed():
        return TaskStatus(task_id=task_id, status="FAILURE", progress=0, error=str(result.result))
    return TaskStatus(
        task_id=task_id,
        status=result.state,
        progress=int(info.get("progress", 0)),
        stage=info.get("stage"),
        message=info.get("message"),
    )


@app.get("/api/v1/qc/{task_id}/artifacts/{artifact_name}")
def get_artifact(task_id: str, artifact_name: str) -> FileResponse:
    if artifact_name not in ALLOWED_ARTIFACTS:
        raise HTTPException(status_code=404, detail="Artifact not found")
    result = AsyncResult(task_id, app=celery_app)
    if not result.successful() or not isinstance(result.result, dict):
        raise HTTPException(status_code=409, detail="Task has not completed")
    relative_path = result.result.get("artifacts", {}).get(artifact_name)
    if not relative_path:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = (JOB_ROOT / task_id / Path(relative_path)).resolve()
    if JOB_ROOT.resolve() not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)
