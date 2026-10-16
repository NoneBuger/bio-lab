from pathlib import Path

from app.qc import run_qc
from scripts.create_mock_data import create_mock_data


def test_mock_qc_writes_expected_outputs(tmp_path: Path) -> None:
    input_path = create_mock_data(tmp_path / "mock.h5ad")
    result = run_qc(input_path, tmp_path / "qc")

    assert result["before"] == {"cells": 120, "genes": 300}
    assert result["after"]["cells"] < result["before"]["cells"]
    assert result["after"]["genes"] < result["before"]["genes"]
    for name in ("qc_before.png", "qc_after.png", "qc_report.md", "provenance.json"):
        assert (tmp_path / "qc" / name).exists()
