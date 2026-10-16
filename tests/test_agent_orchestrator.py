import pytest

from backend.agent_orchestrator import OrchestrationError, generate_code, orchestrate_qc
from scripts.create_mock_data import create_mock_data


class FakeResponse:
    def __init__(self, code: str):
        self.output_text = code


class FakeResponses:
    def __init__(self, code: str):
        self.code = code

    def create(self, **kwargs):
        return FakeResponse(self.code)


class FakeClient:
    def __init__(self, code: str):
        self.responses = FakeResponses(code)


SAFE_CODE = """summary = run_qc(INPUT_PATH, OUTPUT_DIR / 'qc', min_genes=MIN_GENES, min_cells=MIN_CELLS, max_mito_pct=MAX_MITO_PCT)
assessment = assess_qc(INPUT_PATH, OUTPUT_DIR / 'omics_scientist' / 'qc_assessment.md')"""


def test_orchestrator_executes_mocked_safe_code(tmp_path) -> None:
    input_path = create_mock_data(tmp_path / "sample.h5ad")
    result = orchestrate_qc(
        "完成 QC",
        input_path,
        tmp_path / "output",
        min_genes=200,
        min_cells=3,
        max_mito_pct=20.0,
        client=FakeClient(SAFE_CODE),
    )
    assert "summary" in result
    assert "assessment" in result


def test_orchestrator_blocks_malicious_openai_code(tmp_path) -> None:
    malicious = "import os as o\nsummary = run_qc(INPUT_PATH, OUTPUT_DIR)\nassessment = {}"
    with pytest.raises(OrchestrationError, match="安全沙盒拦截"):
        orchestrate_qc(
            "完成 QC",
            tmp_path / "sample.h5ad",
            tmp_path / "output",
            min_genes=200,
            min_cells=3,
            max_mito_pct=20.0,
            client=FakeClient(malicious),
        )


def test_orchestrator_requires_api_key(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(OrchestrationError, match="OPENAI_API_KEY"):
        generate_code("完成 QC")
