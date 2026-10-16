"""Small HTTP client used by the Streamlit frontend."""

from __future__ import annotations

from typing import Any

import requests


def submit_qc(
    base_url: str,
    file_bytes: bytes,
    filename: str,
    instruction: str,
    min_genes: int,
    min_cells: int,
    max_mito_pct: float,
) -> dict[str, Any]:
    response = requests.post(
        f"{base_url.rstrip('/')}/api/v1/qc",
        files={"file": (filename, file_bytes, "application/octet-stream")},
        data={
            "instruction": instruction,
            "min_genes": min_genes,
            "min_cells": min_cells,
            "max_mito_pct": max_mito_pct,
        },
        timeout=120,
    )
    response.raise_for_status()
    return response.json()


def get_qc_status(base_url: str, task_id: str) -> dict[str, Any]:
    response = requests.get(
        f"{base_url.rstrip('/')}/api/v1/qc/{task_id}", timeout=30
    )
    response.raise_for_status()
    return response.json()


def get_artifact(base_url: str, task_id: str, artifact_name: str) -> bytes:
    response = requests.get(
        f"{base_url.rstrip('/')}/api/v1/qc/{task_id}/artifacts/{artifact_name}",
        timeout=120,
    )
    response.raise_for_status()
    return response.content
