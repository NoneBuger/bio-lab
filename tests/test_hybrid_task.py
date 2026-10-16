from pathlib import Path

import pytest

from backend import tasks


def fake_qc_result():
    return {
        "generated_code": "summary = ...",
        "summary": {
            "before": {"cells": 10, "genes": 20},
            "candidate_genes": ["CD8A", "GZMB"],
            "cell_types": ["CD8 T cell"],
        },
        "assessment": {"recommendations": ["检查批次"]},
    }


def test_hybrid_runs_qc_before_literature_and_passes_context(tmp_path: Path, monkeypatch) -> None:
    events = []

    def fake_qc(*args, **kwargs):
        events.append("qc")
        callback = kwargs["progress_callback"]
        callback("AI_GENERATING_CODE", 20, "generating")
        callback("EXECUTING_ANALYSIS", 35, "executing")
        callback("ASSESSING_BATCH_EFFECT", 50, "assessing")
        return fake_qc_result()

    def fake_literature(instruction, output_dir, *, qc_context=None):
        events.append(("literature", qc_context))
        return {"status": "no_results", "queries": [], "papers": [], "summary": "none"}

    monkeypatch.setattr(tasks, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(tasks, "orchestrate_qc", fake_qc)
    monkeypatch.setattr(tasks, "run_literature", fake_literature)
    monkeypatch.setattr(tasks.celery_app.conf, "task_always_eager", True)
    result = tasks.run_hybrid_task.apply(
        args=["input.h5ad"], kwargs={"instruction": "QC and literature"}, task_id="hybrid-test"
    ).get()

    assert events[0] == "qc"
    assert events[1][0] == "literature"
    context = events[1][1]
    assert context["candidate_genes"] == ["CD8A", "GZMB"]
    assert context["cell_types"] == ["CD8 T cell"]
    assert result["qc"]["summary"]["before"]["cells"] == 10
    assert result["literature"]["status"] == "no_results"
    assert (tmp_path / "jobs" / "hybrid-test" / "provenance.json").exists()


def test_hybrid_qc_failure_does_not_call_literature(tmp_path: Path, monkeypatch) -> None:
    called = False

    def failing_qc(*args, **kwargs):
        raise RuntimeError("sandbox blocked")

    def literature_should_not_run(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(tasks, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(tasks, "orchestrate_qc", failing_qc)
    monkeypatch.setattr(tasks, "run_literature", literature_should_not_run)
    monkeypatch.setattr(tasks.celery_app.conf, "task_always_eager", True)
    with pytest.raises(RuntimeError, match="sandbox blocked"):
        tasks.run_hybrid_task.apply(
            args=["input.h5ad"], kwargs={"instruction": "QC and literature"}, task_id="hybrid-fail"
        ).get()

    assert called is False
