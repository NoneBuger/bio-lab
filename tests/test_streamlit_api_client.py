from app import api_client
import requests
import pytest


class FakeResponse:
    content = b"artifact"

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return {"task_id": "task-1", "status": "PENDING"}


def test_api_client_submit_status_and_artifact(monkeypatch) -> None:
    calls = []

    def fake_post(url, **kwargs):
        calls.append(("post", url, kwargs))
        return FakeResponse()

    def fake_get(url, **kwargs):
        calls.append(("get", url, kwargs))
        return FakeResponse()

    monkeypatch.setattr(api_client.requests, "post", fake_post)
    monkeypatch.setattr(api_client.requests, "get", fake_get)

    submitted = api_client.submit_qc("http://api", b"data", "sample.h5ad", "qc", 200, 3, 20.0)
    status = api_client.get_qc_status("http://api", "task-1")
    artifact = api_client.get_artifact("http://api", "task-1", "qc_before")

    assert submitted["task_id"] == "task-1"
    assert status["status"] == "PENDING"
    assert artifact == b"artifact"
    assert calls[0][1] == "http://api/api/v1/qc"
    assert calls[1][1] == "http://api/api/v1/qc/task-1"


def test_submit_task_supports_agent_type_and_optional_file(monkeypatch) -> None:
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(api_client.requests, "post", fake_post)
    api_client.submit_task("http://api", agent_type="literature", instruction="TP53 文献")
    assert captured["files"] is None
    assert captured["data"]["agent_type"] == "literature"

    api_client.submit_task(
        "http://api", agent_type="hybrid", file_bytes=b"h5ad", filename="sample.h5ad"
    )
    assert captured["files"]["file"][0] == "sample.h5ad"


def test_poll_task_uses_progressive_backoff(monkeypatch) -> None:
    statuses = iter([
        {"status": "PENDING", "progress": 0},
        {"status": "PROGRESS", "progress": 20},
        {"status": "PROGRESS", "progress": 35},
        {"status": "PROGRESS", "progress": 65},
        {"status": "PROGRESS", "progress": 80},
        {"status": "SUCCESS", "progress": 100, "result": {}},
    ])
    sleeps = []
    monkeypatch.setattr(api_client, "get_task_status", lambda *_: next(statuses))
    result = api_client.poll_task(
        "http://api", "task-1", timeout_seconds=100, sleep_fn=sleeps.append, monotonic_fn=lambda: 0
    )
    assert result["status"] == "SUCCESS"
    assert sleeps == [2.0, 2.0, 2.0, 3.0, 5.0]


def test_get_task_artifact_failure_is_explicit(monkeypatch) -> None:
    class FailedResponse(FakeResponse):
        def raise_for_status(self):
            raise requests.HTTPError("404")

    monkeypatch.setattr(api_client.requests, "get", lambda *_args, **_kwargs: FailedResponse())
    with pytest.raises(api_client.BioLabAPIError, match="API 请求失败"):
        api_client.get_task_artifact("http://api", "task-1", "missing")
