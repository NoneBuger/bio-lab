"""Asynchronous Scanpy tasks executed by Celery workers."""

from __future__ import annotations

import os
from pathlib import Path

from .agent_orchestrator import orchestrate_qc
from .celery_app import celery_app


JOB_ROOT = Path(os.getenv("BIO_LAB_JOB_DIR", "output/jobs"))


def _progress(task, percent: int, stage: str, message: str) -> None:
    # Eager mode is used by tests when Redis is unavailable. The task result
    # remains available locally, while real workers still publish progress.
    if celery_app.conf.task_always_eager:
        return
    task.update_state(
        state="PROGRESS",
        meta={"progress": percent, "stage": stage, "message": message},
    )


@celery_app.task(bind=True, name="backend.tasks.run_qc_task")
def run_qc_task(
    self,
    input_path: str,
    instruction: str = "",
    min_genes: int = 200,
    min_cells: int = 3,
    max_mito_pct: float = 20.0,
) -> dict[str, object]:
    """Run QC and batch-effect assessment in a worker process."""
    task_id = self.request.id
    job_dir = JOB_ROOT / task_id
    _progress(self, 5, "RECEIVED", "任务已进入 Celery worker")
    def report(stage: str, percent: int, message: str) -> None:
        _progress(self, percent, stage, message)

    orchestration = orchestrate_qc(
        instruction or "完成基础单细胞 QC 并评估批次效应",
        input_path,
        job_dir,
        min_genes=min_genes,
        min_cells=min_cells,
        max_mito_pct=max_mito_pct,
        progress_callback=report,
    )
    summary = orchestration["summary"]
    assessment = orchestration["assessment"]
    _progress(self, 90, "BATCH_ASSESSMENT_COMPLETED", "批次效应评估已完成")
    _progress(self, 95, "FINALIZING", "正在整理分析结果")
    """The orchestrator owns execution; artifacts are stable contract paths."""
    artifacts = {
        "qc_report": "qc/qc_report.md",
        "qc_summary": "qc/qc_summary.json",
        "provenance": "qc/provenance.json",
        "qc_before": "qc/qc_before.png",
        "qc_after": "qc/qc_after.png",
        "qc_before_scatter": "qc/qc_before_scatter.png",
        "qc_after_scatter": "qc/qc_after_scatter.png",
        "assessment_report": "omics_scientist/qc_assessment.md",
        "assessment_json": "omics_scientist/qc_assessment.json",
    }
    return {
        "task_id": task_id,
        "instruction": instruction,
        "generated_code": orchestration["generated_code"],
        "summary": summary,
        "assessment": assessment,
        "artifacts": artifacts,
    }
