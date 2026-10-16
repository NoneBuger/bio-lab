"""HTTP client for the asynchronous Bio Lab backend."""

from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any

import requests


class BioLabAPIError(RuntimeError):
    """A backend request failed or the backend could not be reached."""


def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}{path}"


def _raise_for_response(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.RequestException as exc:
        raise BioLabAPIError(f"Bio Lab API 请求失败：{exc}") from exc


def submit_task(
    base_url: str,
    *,
    agent_type: str = "auto",
    instruction: str = "",
    file_bytes: bytes | None = None,
    filename: str | None = None,
    min_genes: int = 200,
    min_cells: int = 3,
    max_mito_pct: float = 20.0,
) -> dict[str, Any]:
    """Submit an analysis task, optionally including an h5ad file."""
    files = None
    if file_bytes is not None and filename:
        files = {"file": (filename, file_bytes, "application/octet-stream")}
    try:
        response = requests.post(
            _url(base_url, "/api/v1/qc"),
            files=files,
            data={
                "agent_type": agent_type,
                "instruction": instruction,
                "min_genes": min_genes,
                "min_cells": min_cells,
                "max_mito_pct": max_mito_pct,
            },
            timeout=120,
        )
        _raise_for_response(response)
        return response.json()
    except BioLabAPIError:
        raise
    except requests.RequestException as exc:
        raise BioLabAPIError(f"无法连接分析后端：{exc}") from exc


def poll_task(
    base_url: str,
    task_id: str,
    *,
    timeout_minutes: float | None = None,
    timeout_seconds: float | None = None,
    on_status: Callable[[dict[str, Any]], None] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    monotonic_fn: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """Poll a task with 2, 2, 2, 3, 5, ... second backoff up to 10 seconds."""
    if timeout_seconds is None:
        minutes = timeout_minutes
        if minutes is None:
            minutes = float(os.getenv("POLL_TIMEOUT_MINUTES", "30"))
        timeout_seconds = minutes * 60
    started = monotonic_fn()
    delays = (2.0, 2.0, 2.0, 3.0, 5.0, 10.0)
    poll_count = 0
    while True:
        status = get_task_status(base_url, task_id)
        if on_status:
            on_status(status)
        if status.get("status") in {"SUCCESS", "FAILURE", "REVOKED"}:
            return status
        elapsed = monotonic_fn() - started
        if elapsed >= timeout_seconds:
            raise TimeoutError("任务执行超时，请检查数据规模或联系管理员")
        sleep_fn(delays[min(poll_count, len(delays) - 1)])
        poll_count += 1


def get_task_status(base_url: str, task_id: str) -> dict[str, Any]:
    try:
        response = requests.get(_url(base_url, f"/api/v1/tasks/{task_id}"), timeout=30)
        _raise_for_response(response)
        return response.json()
    except BioLabAPIError:
        raise
    except requests.RequestException as exc:
        raise BioLabAPIError(f"无法连接分析后端：{exc}") from exc


def get_task_artifact(base_url: str, task_id: str, artifact_name: str) -> bytes:
    try:
        response = requests.get(
            _url(base_url, f"/api/v1/qc/{task_id}/artifacts/{artifact_name}"),
            timeout=120,
        )
        _raise_for_response(response)
        return response.content
    except BioLabAPIError:
        raise
    except requests.RequestException as exc:
        raise BioLabAPIError(f"无法下载任务结果：{exc}") from exc


# Backwards-compatible names used by older integrations.
def submit_qc(
    base_url: str,
    file_bytes: bytes,
    filename: str,
    instruction: str,
    min_genes: int,
    min_cells: int,
    max_mito_pct: float,
) -> dict[str, Any]:
    return submit_task(
        base_url,
        agent_type="data_analyst",
        file_bytes=file_bytes,
        filename=filename,
        instruction=instruction,
        min_genes=min_genes,
        min_cells=min_cells,
        max_mito_pct=max_mito_pct,
    )


def get_qc_status(base_url: str, task_id: str) -> dict[str, Any]:
    try:
        response = requests.get(_url(base_url, f"/api/v1/qc/{task_id}"), timeout=30)
        _raise_for_response(response)
        return response.json()
    except BioLabAPIError:
        raise
    except requests.RequestException as exc:
        raise BioLabAPIError(f"无法连接分析后端：{exc}") from exc


def get_artifact(base_url: str, task_id: str, artifact_name: str) -> bytes:
    return get_task_artifact(base_url, task_id, artifact_name)
