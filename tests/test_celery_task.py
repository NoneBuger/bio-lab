from pathlib import Path

from app.omics_scientist import assess_qc
from backend import tasks
from scripts.create_mock_data import create_mock_data


def test_celery_qc_task_runs_without_redis_in_eager_mode(tmp_path: Path, monkeypatch) -> None:
    input_path = create_mock_data(tmp_path / "sample.h5ad")
    monkeypatch.setattr(tasks, "JOB_ROOT", tmp_path / "jobs")
    tasks.celery_app.conf.task_always_eager = True
    result = tasks.run_qc_task.apply(
        args=[str(input_path)],
        kwargs={"instruction": "test", "min_genes": 200, "min_cells": 3, "max_mito_pct": 20.0},
        task_id="test-task",
    ).get()

    assert result["task_id"] == "test-task"
    assert result["summary"]["after"]["cells"] > 0
    assert (tmp_path / "jobs" / "test-task" / "qc" / "qc_report.md").exists()
    tasks.celery_app.conf.task_always_eager = False
