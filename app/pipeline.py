"""Application-facing orchestration for one isolated QC job."""

from __future__ import annotations

import json
import tempfile
import uuid
from pathlib import Path

try:
    from qc import run_qc  # Streamlit executes app/app.py from this directory.
except ModuleNotFoundError:
    from app.qc import run_qc
from scripts.omics_scientist_qc import assess_qc


def execute_qc_job(
    file_bytes: bytes,
    output_root: str | Path,
    *,
    min_genes: int = 200,
    min_cells: int = 3,
    max_mito_pct: float = 20.0,
) -> dict[str, object]:
    """Persist one upload in a temporary file and run both QC stages."""
    job_id = uuid.uuid4().hex[:12]
    output_dir = Path(output_root) / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(suffix=".h5ad", delete=False) as handle:
        handle.write(file_bytes)
        input_path = Path(handle.name)

    try:
        summary = run_qc(
            input_path,
            output_dir / "qc",
            min_genes=min_genes,
            min_cells=min_cells,
            max_mito_pct=max_mito_pct,
        )
        assessment = assess_qc(
            input_path, output_dir / "omics_scientist" / "qc_assessment.md"
        )
    finally:
        input_path.unlink(missing_ok=True)

    (output_dir / "job.json").write_text(
        json.dumps({"job_id": job_id, "summary": summary, "assessment": assessment}, indent=2),
        encoding="utf-8",
    )
    return {
        "job_id": job_id,
        "output_dir": output_dir,
        "summary": summary,
        "assessment": assessment,
    }
