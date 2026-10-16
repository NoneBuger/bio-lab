"""OpenAI-backed natural-language analysis orchestration."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from openai import OpenAI

from app.omics_scientist import assess_qc
from app.qc import run_qc

from .sandbox import SandboxViolation, execute_generated_code


SYSTEM_PROMPT = """You are a conservative single-cell RNA-seq analysis orchestrator.
Convert the user's instruction into Python code for the existing Bio Lab QC functions.

The only analysis functions allowed are run_qc and assess_qc. They are already present
in the execution environment. Available variables are INPUT_PATH, OUTPUT_DIR,
MIN_GENES, MIN_CELLS, MAX_MITO_PCT, and INSTRUCTION.

The code must assign `summary` from run_qc and `assessment` from assess_qc, in that order.
Use OUTPUT_DIR / "qc" for run_qc and OUTPUT_DIR / "omics_scientist" / "qc_assessment.md"
for assess_qc. Do not reimplement analysis logic.

Return Python code only. Never import or call os, sys, subprocess, shutil, socket,
requests, pathlib, open, eval, exec, compile, or __import__. Do not access dunder
attributes, environment variables, network resources, or files outside OUTPUT_DIR.
Reject requests for unsupported analyses instead of inventing code.
"""


class OrchestrationError(RuntimeError):
    """Raised when code generation or execution cannot safely proceed."""


def _extract_code(text: str) -> str:
    match = re.search(r"```(?:python)?\s*(.*?)```", text, flags=re.DOTALL | re.IGNORECASE)
    return (match.group(1) if match else text).strip()


def generate_code(instruction: str, client: OpenAI | None = None) -> str:
    if not os.getenv("OPENAI_API_KEY") and client is None:
        raise OrchestrationError(
            "OPENAI_API_KEY is not configured. Please set it before running AI orchestration."
        )
    client = client or OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    response = client.responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
        instructions=SYSTEM_PROMPT,
        input=instruction,
    )
    text = getattr(response, "output_text", None)
    if not text:
        raise OrchestrationError("OpenAI returned no executable analysis code")
    return _extract_code(text)


def orchestrate_qc(
    instruction: str,
    input_path: str | Path,
    output_dir: str | Path,
    *,
    min_genes: int,
    min_cells: int,
    max_mito_pct: float,
    progress_callback: Callable[[str, int, str], None] | None = None,
    client: OpenAI | None = None,
) -> dict[str, object]:
    def progress(stage: str, percent: int, message: str) -> None:
        if progress_callback:
            progress_callback(stage, percent, message)

    progress("AI_GENERATING_CODE", 10, "AI 正在生成分析代码")
    code = generate_code(instruction, client=client)
    progress("EXECUTING_ANALYSIS", 45, "正在执行 QC 分析")
    context = {
        "INPUT_PATH": Path(input_path),
        "OUTPUT_DIR": Path(output_dir),
        "MIN_GENES": min_genes,
        "MIN_CELLS": min_cells,
        "MAX_MITO_PCT": max_mito_pct,
        "INSTRUCTION": instruction,
        "run_qc": run_qc,
        "assess_qc": assess_qc,
    }
    try:
        values = execute_generated_code(code, context)
    except SandboxViolation as exc:
        raise OrchestrationError(f"AI 生成代码被安全沙盒拦截：{exc}") from exc
    progress("ASSESSING_BATCH_EFFECT", 75, "正在评估批次效应")
    if "summary" not in values or "assessment" not in values:
        raise OrchestrationError("Generated code did not return summary and assessment")
    return {
        "generated_code": code,
        "summary": values["summary"],
        "assessment": values["assessment"],
    }
