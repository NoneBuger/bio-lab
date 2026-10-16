from pathlib import Path

from app.pipeline import execute_qc_job
from scripts.create_mock_data import create_mock_data


def test_execute_qc_job_isolates_results(tmp_path: Path) -> None:
    input_path = create_mock_data(tmp_path / "mock.h5ad")
    result = execute_qc_job(input_path.read_bytes(), tmp_path / "runs")
    output_dir = Path(result["output_dir"])

    assert len(result["job_id"]) == 12
    assert (output_dir / "qc" / "qc_report.md").exists()
    assert (output_dir / "omics_scientist" / "qc_assessment.md").exists()
    assert not list(tmp_path.glob("tmp*.h5ad"))
