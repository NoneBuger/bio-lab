from app import api_client


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
