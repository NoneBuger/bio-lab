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
from .router import route_instruction
from .tasks import JOB_ROOT, run_hybrid_task, run_literature_task, run_qc_task


app = FastAPI(title="Bio Lab API", version="0.2.0")
MAX_UPLOAD_SIZE_GB = float(os.getenv("MAX_UPLOAD_SIZE_GB", "5"))
MAX_UPLOAD_BYTES = int(MAX_UPLOAD_SIZE_GB * 1024**3)
MAX_CHUNK_SIZE = 1024 * 1024
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
    "literature_report",
    "literature_json",
}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/qc", response_model=TaskSubmitted, status_code=202)
async def submit_qc(
    file: UploadFile | None = File(default=None),
    instruction: str = Form(default=""),
    agent_type: str = Form(default="auto"),
    min_genes: int = Form(default=200),
    min_cells: int = Form(default=3),
    max_mito_pct: float = Form(default=20.0),
) -> TaskSubmitted:
    # Direct unit-test calls do not pass through FastAPI's dependency
    # conversion and therefore may receive the Form default object itself.
    if not isinstance(instruction, str):
        instruction = ""
    if not isinstance(agent_type, str):
        agent_type = "auto"
    if not isinstance(min_genes, int):
        min_genes = 200
    if not isinstance(min_cells, int):
        min_cells = 3
    if not isinstance(max_mito_pct, (int, float)):
        max_mito_pct = 20.0
    try:
        route = route_instruction(instruction, requested_agent_type=agent_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    selected_agent = route["agent_type"]
    if selected_agent in {"data_analyst", "hybrid"} and file is None:
        raise HTTPException(status_code=400, detail="An .h5ad file is required for this agent type")
    if file is not None and (not file.filename or not file.filename.lower().endswith(".h5ad")):
        raise HTTPException(status_code=400, detail="Only .h5ad files are supported")
    if min_genes < 0 or min_cells < 1 or not 0 <= max_mito_pct <= 100:
        raise HTTPException(status_code=400, detail="Invalid QC parameters")

    task_id = str(uuid.uuid4())
    input_path: Path | None = None
    if file is not None:
        input_path = JOB_ROOT / task_id / "input" / "sample.h5ad"
        input_path.parent.mkdir(parents=True, exist_ok=True)
        total_bytes = 0
        with input_path.open("wb") as target:
            while chunk := await file.read(MAX_CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > MAX_UPLOAD_BYTES:
                    input_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件超过 {MAX_UPLOAD_SIZE_GB:g} GB 限制",
                    )
                target.write(chunk)

    kwargs = {
        "instruction": instruction,
        "min_genes": min_genes,
        "min_cells": min_cells,
        "max_mito_pct": max_mito_pct,
    }
    if selected_agent == "literature":
        run_literature_task.apply_async(args=[], kwargs={"instruction": instruction}, task_id=task_id)
    elif selected_agent == "hybrid":
        run_hybrid_task.apply_async(args=[str(input_path)], kwargs=kwargs, task_id=task_id)
    else:
        run_qc_task.apply_async(args=[str(input_path)], kwargs=kwargs, task_id=task_id)
    return TaskSubmitted(task_id=task_id)


@app.get("/api/v1/qc/{task_id}", response_model=TaskStatus)
def get_qc_status(task_id: str) -> TaskStatus:
    result = AsyncResult(task_id, app=celery_app)
    raw_info = result.info
    info = raw_info if isinstance(raw_info, dict) else {}
    if result.successful():
        return TaskStatus(task_id=task_id, status="SUCCESS", progress=100, result=result.result)
    if result.failed():
        failure_info = raw_info if isinstance(raw_info, dict) else {}
        fallback_error = str(raw_info) if raw_info is not None else str(result.result)
        error = failure_info.get("error", fallback_error)
        return TaskStatus(
            task_id=task_id,
            status="FAILURE",
            progress=0,
            stage=failure_info.get("stage"),
            message=failure_info.get("message") or f"任务执行失败：{error}",
            error=error,
        )
    return TaskStatus(
        task_id=task_id,
        status=result.state,
        progress=int(info.get("progress", 0)),
        stage=info.get("stage"),
        message=info.get("message"),
    )


@app.get("/api/v1/tasks/{task_id}", response_model=TaskStatus)
def get_task_status(task_id: str) -> TaskStatus:
    """Unified task-status endpoint; kept equivalent to the QC alias."""
    return get_qc_status(task_id)


@app.get("/api/v1/tasks/{task_id}/artifacts/{artifact_name}")
@app.get("/api/v1/qc/{task_id}/artifacts/{artifact_name}")
def get_artifact(task_id: str, artifact_name: str) -> FileResponse:
    result = AsyncResult(task_id, app=celery_app)
    if not result.successful() or not isinstance(result.result, dict):
        raise HTTPException(status_code=409, detail="Task has not completed")
    artifacts = result.result.get("artifacts", {})
    if not isinstance(artifacts, dict):
        raise HTTPException(status_code=404, detail="Artifact not found")

    job_root = (JOB_ROOT / task_id).resolve()
    mapped_paths = {str(value) for value in artifacts.values() if isinstance(value, str)}
    requested_path = Path(artifact_name)
    direct_path = (job_root / requested_path).resolve()
    is_safe_relative = not requested_path.is_absolute() and requested_path == Path(artifact_name)

    # Accept a mapped physical filename for backward compatibility, while
    # logical names (for example, literature_report) resolve via artifacts.
    if is_safe_relative and artifact_name in mapped_paths and direct_path.is_file():
        relative_path = artifact_name
    else:
        relative_path = artifacts.get(artifact_name)
    if not relative_path:
        raise HTTPException(status_code=404, detail="Artifact not found")
    path = (job_root / Path(relative_path)).resolve()
    if job_root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return FileResponse(path)
