from pathlib import Path

from backend.agent_orchestrator import orchestrate_qc
from backend import tasks
from scripts.create_mock_data import create_mock_data


class FakeResponse:
    output_text = """summary = run_qc(INPUT_PATH, OUTPUT_DIR / 'qc', min_genes=MIN_GENES, min_cells=MIN_CELLS, max_mito_pct=MAX_MITO_PCT)
assessment = assess_qc(INPUT_PATH, OUTPUT_DIR / 'omics_scientist' / 'qc_assessment.md')"""


class FakeResponses:
    def create(self, **kwargs):
        return FakeResponse()


class FakeClient:
    responses = FakeResponses()


def test_celery_qc_task_runs_without_redis_in_eager_mode(tmp_path: Path, monkeypatch) -> None:
    input_path = create_mock_data(tmp_path / "sample.h5ad")
    monkeypatch.setattr(tasks, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(
        tasks,
        "orchestrate_qc",
        lambda *args, **kwargs: orchestrate_qc(*args, client=FakeClient(), **kwargs),
    )
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


def test_invalid_openai_key_failure_meta_is_explicit(monkeypatch) -> None:
    class FakeTask:
        def __init__(self) -> None:
            self.states = []

        def update_state(self, **kwargs) -> None:
            self.states.append(kwargs)

    fake_task = FakeTask()
    monkeypatch.setattr(tasks.celery_app.conf, "task_always_eager", False)

    tasks._mark_failure(
        fake_task,
        "EXTRACTING_ENTITIES",
        RuntimeError("OPENAI_API_KEY 无效或未配置"),
    )

    assert fake_task.states == [
        {
            "state": "FAILURE",
            "meta": {
                "progress": 0,
                "stage": "EXTRACTING_ENTITIES",
                "message": "OPENAI_API_KEY 无效或未配置",
                "error": "OPENAI_API_KEY 无效或未配置",
            },
        }
    ]
