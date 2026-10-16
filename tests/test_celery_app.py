import os
import subprocess
import sys
from pathlib import Path
from unittest import mock

from celery import Celery

import backend.main as backend_main


def _load_config_in_clean_process(*, eager: str | None, redis_url: str | None = None) -> str:
    env = os.environ.copy()
    for name in ("CELERY_TASK_ALWAYS_EAGER", "CELERY_BROKER_URL", "CELERY_RESULT_BACKEND", "REDIS_URL"):
        env.pop(name, None)
    if eager is not None:
        env["CELERY_TASK_ALWAYS_EAGER"] = eager
    if redis_url is not None:
        env["REDIS_URL"] = redis_url
    code = (
        "from backend.celery_app import celery_app; "
        "print(repr((celery_app.conf.task_always_eager, "
        "celery_app.conf.result_backend, "
        "celery_app.conf.task_store_eager_result, "
        "celery_app.conf.result_backend_max_entries)))"
    )
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_eager_mode_uses_memory_backend_without_redis() -> None:
    assert _load_config_in_clean_process(eager="TRUE") == (
        "(True, 'cache+memory://', True, 10000)"
    )


def test_truthy_eager_values_are_case_and_format_insensitive() -> None:
    for value in ("true", "True", "TRUE", "1", "yes", "on"):
        assert _load_config_in_clean_process(eager=value).startswith("(True, 'cache+memory://'")


def test_non_eager_mode_keeps_redis_backend() -> None:
    assert _load_config_in_clean_process(eager=None, redis_url="redis://redis-host:6379") == (
        "(False, 'redis://redis-host:6379/1', False, None)"
    )


def test_eager_mode_does_not_connect_to_redis() -> None:
    app = Celery("eager-connection-test", broker="redis://localhost:6379/0", backend="cache+memory://")
    app.conf.update(task_always_eager=True, task_store_eager_result=True)

    @app.task(name="eager-connection-test.task")
    def task() -> dict[str, str]:
        return {"status": "ok"}

    with mock.patch("redis.connection.Connection.connect") as mock_connect:
        result = task.apply_async(task_id="eager-no-redis")
        assert result.get() == {"status": "ok"}
        assert result.info == {"status": "ok"}

    mock_connect.assert_not_called()


def test_api_can_query_eager_result_without_redis(monkeypatch, tmp_path: Path) -> None:
    app = Celery("api-eager-status-test", broker="memory://", backend="cache+memory://")
    app.conf.update(task_always_eager=True, task_store_eager_result=True)

    @app.task(name="api-eager-status-test.literature")
    def literature_task() -> dict[str, object]:
        return {"task_id": "api-eager-status", "artifacts": {}}

    class FakeUploadTask:
        def apply_async(self, *, task_id: str, **kwargs: object):
            return literature_task.apply_async(task_id=task_id)

    monkeypatch.setattr(backend_main, "celery_app", app)
    monkeypatch.setattr(backend_main, "run_literature_task", FakeUploadTask())
    monkeypatch.setattr(backend_main, "JOB_ROOT", tmp_path)

    response = __import__("asyncio").run(
        backend_main.submit_qc(
            file=None,
            instruction="检索 CD8 T cell 文献",
            agent_type="literature",
        )
    )
    status = backend_main.get_task_status(response.task_id)

    assert status.status == "SUCCESS"
    assert status.result == {"task_id": "api-eager-status", "artifacts": {}}


def test_api_reports_eager_task_failure_without_redis(monkeypatch) -> None:
    app = Celery("api-eager-failure-test", broker="memory://", backend="cache+memory://")
    app.conf.update(
        task_always_eager=True,
        task_eager_propagates=False,
        task_store_eager_result=True,
    )

    @app.task(name="api-eager-failure-test.task")
    def failing_task() -> None:
        raise RuntimeError("intentional probe failure")

    result = failing_task.apply_async(task_id="api-eager-failure")
    monkeypatch.setattr(backend_main, "celery_app", app)

    assert result.state == "FAILURE"
    assert "intentional probe failure" in str(result.info)

    status = backend_main.get_task_status("api-eager-failure")
    assert status.status == "FAILURE"
    assert "intentional probe failure" in (status.error or "")
    assert status.message == "任务执行失败：intentional probe failure"
