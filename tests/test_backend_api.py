import asyncio
from pathlib import Path

import backend.main as backend_main
import pytest
from fastapi import HTTPException


class FakeUpload:
    def __init__(self, filename: str, content: bytes) -> None:
        self.filename = filename
        self.content = content
        self.read_offset = 0

    async def read(self, size: int) -> bytes:
        chunk = self.content[self.read_offset : self.read_offset + size]
        self.read_offset += len(chunk)
        return chunk


class FakeTask:
    def __init__(self) -> None:
        self.task_id = None
        self.kwargs = None

    def apply_async(self, *, task_id: str, **kwargs: object) -> None:
        self.task_id = task_id
        self.kwargs = kwargs


class FakeResult:
    state = "PROGRESS"
    info = {"progress": 35, "stage": "RUNNING", "message": "working"}
    result = None

    def successful(self) -> bool:
        return False

    def failed(self) -> bool:
        return False


def test_submit_and_query_qc_task(monkeypatch, tmp_path: Path) -> None:
    fake_task = FakeTask()
    monkeypatch.setattr(backend_main, "run_qc_task", fake_task)
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "AsyncResult", lambda task_id, app: FakeResult())
    response = asyncio.run(
        backend_main.submit_qc(
            file=FakeUpload("sample.h5ad", b"not-analyzed-yet"),
            instruction="run qc",
            min_genes=200,
            min_cells=3,
            max_mito_pct=20.0,
        )
    )

    task_id = response.task_id
    assert fake_task.task_id == task_id
    assert (tmp_path / task_id / "input" / "sample.h5ad").exists()

    status = backend_main.get_qc_status(task_id)
    assert status.progress == 35


def test_reject_non_h5ad_upload() -> None:
    try:
        asyncio.run(
            backend_main.submit_qc(
                file=FakeUpload("sample.csv", b"x"),
            )
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("invalid extension should be rejected")


def test_literature_task_does_not_require_file(monkeypatch, tmp_path: Path) -> None:
    fake_task = FakeTask()
    monkeypatch.setattr(backend_main, "run_literature_task", fake_task)
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)
    response = asyncio.run(
        backend_main.submit_qc(
            file=None,
            instruction="检索 TP53 文献",
            agent_type="literature",
        )
    )
    assert response.task_id == fake_task.task_id
    assert fake_task.kwargs["args"] == []


@pytest.mark.parametrize("agent_type", ["data_analyst", "hybrid"])
def test_data_agents_require_h5ad(agent_type: str) -> None:
    try:
        asyncio.run(backend_main.submit_qc(file=None, agent_type=agent_type))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("data agents should require an h5ad file")


def test_invalid_agent_type_returns_400() -> None:
    try:
        asyncio.run(backend_main.submit_qc(file=None, agent_type="invalid"))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 400
    else:
        raise AssertionError("invalid agent type should be rejected")


def test_upload_limit_interrupts_and_removes_partial_file(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "MAX_UPLOAD_BYTES", 10)
    upload = FakeUpload("large.h5ad", b"01234567890")

    try:
        asyncio.run(
            backend_main.submit_qc(
                file=upload,
                instruction="run qc",
                agent_type="data_analyst",
            )
        )
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 413
        assert "限制" in str(getattr(exc, "detail", ""))
    else:
        raise AssertionError("oversized upload should be rejected")

    assert not list(tmp_path.rglob("*.h5ad"))


def test_unified_task_status_matches_qc_alias(monkeypatch) -> None:
    monkeypatch.setattr(backend_main, "AsyncResult", lambda task_id, app: FakeResult())
    assert backend_main.get_task_status("task-1") == backend_main.get_qc_status("task-1")


class CompletedArtifactResult:
    def __init__(self, artifacts: dict[str, str]) -> None:
        self.result = {"artifacts": artifacts}

    def successful(self) -> bool:
        return True


def test_artifact_logical_and_physical_names_are_supported(monkeypatch, tmp_path: Path) -> None:
    task_id = "artifact-task"
    report = tmp_path / task_id / "literature_report.md"
    report.parent.mkdir(parents=True)
    report.write_text("# Literature report\n", encoding="utf-8")
    artifacts = {"literature_report": "literature_report.md"}
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)
    monkeypatch.setattr(backend_main, "AsyncResult", lambda task_id, app: CompletedArtifactResult(artifacts))

    logical = backend_main.get_artifact(task_id, "literature_report")
    physical = backend_main.get_artifact(task_id, "literature_report.md")

    assert Path(logical.path).read_text(encoding="utf-8") == "# Literature report\n"
    assert Path(physical.path).read_text(encoding="utf-8") == "# Literature report\n"


def test_artifact_path_traversal_is_rejected(monkeypatch, tmp_path: Path) -> None:
    task_id = "artifact-task"
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)
    monkeypatch.setattr(
        backend_main,
        "AsyncResult",
        lambda task_id, app: CompletedArtifactResult({"literature_report": "literature_report.md"}),
    )

    with pytest.raises(HTTPException) as exc_info:
        backend_main.get_artifact(task_id, "../../etc/passwd")

    assert exc_info.value.status_code == 404
