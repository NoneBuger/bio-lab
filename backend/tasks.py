"""Asynchronous multi-agent analysis tasks executed by Celery."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent_orchestrator import orchestrate_qc
from .agents.literature_agent import run_literature
from .celery_app import celery_app

JOB_ROOT = Path(os.getenv("BIO_LAB_JOB_DIR", "output/jobs"))

STAGE_PROGRESS = {
    "EXTRACTING_ENTITIES": 10,
    "AI_GENERATING_CODE": 20,
    "EXECUTING_ANALYSIS": 35,
    "ASSESSING_BATCH_EFFECT": 50,
    "SEARCHING_LITERATURE": 65,
    "SUMMARIZING_LITERATURE": 80,
    "FINALIZING": 90,
    "SUCCESS": 100,
    "FAILURE": 0,
}


def update_stage(task: Any, stage: str, message: str) -> None:
    """Publish one consistent progress payload for every task type."""
    if stage not in STAGE_PROGRESS:
        raise ValueError(f"Unknown task stage: {stage}")
    # Celery eager mode is intentionally usable without Redis. The helper is
    # still called, but there is no result backend to publish intermediate
    # state to in that local/test configuration.
    if celery_app.conf.task_always_eager:
        return
    task.update_state(
        state="SUCCESS" if stage == "SUCCESS" else "PROGRESS",
        meta={"progress": STAGE_PROGRESS[stage], "stage": stage, "message": message},
    )


def _mark_failure(task: Any, stage: str, exc: Exception) -> None:
    if celery_app.conf.task_always_eager:
        return
    message = str(exc)
    if "OPENAI_API_KEY" in message or exc.__class__.__name__ == "AuthenticationError":
        message = "OPENAI_API_KEY 无效或未配置"
    task.update_state(
        state="FAILURE",
        meta={
            "progress": STAGE_PROGRESS["FAILURE"],
            "stage": stage,
            "message": message,
            "error": message,
        },
    )


def _write_provenance(path: Path, *, task_id: str, task_type: str, instruction: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(
            {
                "created_at_utc": datetime.now(UTC).isoformat(),
                "task_id": task_id,
                "task_type": task_type,
                "instruction": instruction,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)


def _qc_artifacts() -> dict[str, str]:
    return {
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


def _literature_artifacts() -> dict[str, str]:
    return {
        "literature_report": "literature_report.md",
        "literature_json": "literature.json",
        "provenance": "provenance.json",
    }


def _run_qc(
    task: Any,
    input_path: str,
    job_dir: Path,
    instruction: str,
    min_genes: int,
    min_cells: int,
    max_mito_pct: float,
    stage_tracker: list[str] | None = None,
) -> dict[str, Any]:
    def report(stage: str, _percent: int, message: str) -> None:
        if stage_tracker is not None:
            stage_tracker[0] = stage
        update_stage(task, stage, message)

    return orchestrate_qc(
        instruction or "完成基础单细胞 QC 并评估批次效应",
        input_path,
        job_dir,
        min_genes=min_genes,
        min_cells=min_cells,
        max_mito_pct=max_mito_pct,
        progress_callback=report,
    )


def _qc_context(orchestration: dict[str, Any]) -> dict[str, Any]:
    summary = orchestration.get("summary") or {}
    assessment = orchestration.get("assessment") or {}
    return {
        "candidate_genes": orchestration.get("candidate_genes")
        or summary.get("candidate_genes", []),
        "cell_types": orchestration.get("cell_types")
        or summary.get("cell_types", []),
        "qc_summary": summary,
        "batch_assessment": assessment,
    }


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
    update_stage(self, "AI_GENERATING_CODE", "正在准备 QC 分析")
    try:
        orchestration = _run_qc(
            self, input_path, job_dir, instruction, min_genes, min_cells, max_mito_pct
        )
    except Exception as exc:  # noqa: BLE001 - preserve a useful Celery failure payload.
        _mark_failure(self, "AI_GENERATING_CODE", exc)
        raise
    update_stage(self, "FINALIZING", "正在整理分析结果")
    result = {
        "task_id": task_id,
        "instruction": instruction,
        "generated_code": orchestration["generated_code"],
        "summary": orchestration["summary"],
        "assessment": orchestration["assessment"],
        "artifacts": _qc_artifacts(),
    }
    update_stage(self, "SUCCESS", "QC 分析已完成")
    return result


@celery_app.task(bind=True, name="backend.tasks.run_literature_task")
def run_literature_task(self, instruction: str = "") -> dict[str, object]:
    """Run literature retrieval without requiring an AnnData input file."""
    task_id = self.request.id
    job_dir = JOB_ROOT / task_id
    current_stage = "EXTRACTING_ENTITIES"
    try:
        update_stage(self, current_stage, "正在提取文献检索实体")
        update_stage(self, "SEARCHING_LITERATURE", "正在检索 Europe PMC 文献")
        result = run_literature(instruction, job_dir)
        update_stage(self, "SUMMARIZING_LITERATURE", "正在生成文献结构化摘要")
        _write_provenance(
            job_dir / "provenance.json",
            task_id=task_id,
            task_type="literature",
            instruction=instruction,
        )
        update_stage(self, "FINALIZING", "正在整理文献报告")
        output = {
            "task_id": task_id,
            "instruction": instruction,
            **result,
            "artifacts": _literature_artifacts(),
        }
        update_stage(self, "SUCCESS", "文献分析已完成")
        return output
    except Exception as exc:  # noqa: BLE001 - retain stage metadata.
        _mark_failure(self, current_stage, exc)
        raise


@celery_app.task(bind=True, name="backend.tasks.run_hybrid_task")
def run_hybrid_task(
    self,
    input_path: str,
    instruction: str = "",
    min_genes: int = 200,
    min_cells: int = 3,
    max_mito_pct: float = 20.0,
) -> dict[str, object]:
    """Run QC first, then literature analysis enriched with QC context."""
    task_id = self.request.id
    job_dir = JOB_ROOT / task_id
    current_stage = "EXTRACTING_ENTITIES"
    try:
        update_stage(self, current_stage, "正在准备复合任务")
        stage_tracker = [current_stage]
        orchestration = _run_qc(
            self, input_path, job_dir, instruction, min_genes, min_cells, max_mito_pct,
            stage_tracker=stage_tracker,
        )
        current_stage = stage_tracker[0]
        qc_context = _qc_context(orchestration)
        current_stage = "SEARCHING_LITERATURE"
        update_stage(self, current_stage, "正在基于 QC 结果检索文献")
        literature = run_literature(instruction, job_dir, qc_context=qc_context)
        update_stage(self, "SUMMARIZING_LITERATURE", "正在生成文献结构化摘要")
        _write_provenance(
            job_dir / "provenance.json",
            task_id=task_id,
            task_type="hybrid",
            instruction=instruction,
        )
        update_stage(self, "FINALIZING", "正在整理综合分析结果")
        output = {
            "task_id": task_id,
            "instruction": instruction,
            "qc": {
                "generated_code": orchestration["generated_code"],
                "summary": orchestration["summary"],
                "assessment": orchestration["assessment"],
            },
            "literature": literature,
            "qc_context": qc_context,
            "artifacts": {
                **_qc_artifacts(),
                "literature_report": "literature_report.md",
                "literature_json": "literature.json",
            },
        }
        update_stage(self, "SUCCESS", "综合分析已完成")
        return output
    except Exception as exc:  # noqa: BLE001 - preserve the failing stage.
        _mark_failure(self, current_stage, exc)
        raise
