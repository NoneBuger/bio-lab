import pytest

from backend.sandbox import SandboxViolation, execute_generated_code


def test_sandbox_allows_existing_analysis_functions() -> None:
    calls = []

    def run_qc(*args, **kwargs):
        calls.append(("qc", args, kwargs))
        return {"ok": True}

    def assess_qc(*args, **kwargs):
        calls.append(("assessment", args, kwargs))
        return {"ok": True}

    values = execute_generated_code(
        "summary = run_qc(INPUT_PATH, OUTPUT_DIR)\nassessment = assess_qc(INPUT_PATH, OUTPUT_DIR)",
        {"INPUT_PATH": "sample.h5ad", "OUTPUT_DIR": "output", "run_qc": run_qc, "assess_qc": assess_qc},
    )
    assert values["summary"] == {"ok": True}
    assert values["assessment"] == {"ok": True}
    assert len(calls) == 2


@pytest.mark.parametrize(
    "code",
    [
        "import os",
        "import os as o",
        "from os import system",
        "open('/etc/passwd').read()",
        "globals()['__builtins__']",
        "x.__class__",
    ],
)
def test_sandbox_rejects_dangerous_code(code: str) -> None:
    with pytest.raises(SandboxViolation):
        execute_generated_code(code, {})
