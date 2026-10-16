import asyncio
from pathlib import Path

import backend.main as backend_main


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

    def apply_async(self, *, task_id: str, **kwargs: object) -> None:
        self.task_id = task_id


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
