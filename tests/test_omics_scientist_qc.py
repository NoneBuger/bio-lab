from pathlib import Path

import anndata as ad
import numpy as np

from scripts.omics_scientist_qc import assess_qc


def test_report_flags_missing_batch_metadata(tmp_path: Path) -> None:
    adata = ad.AnnData(np.ones((4, 3)))
    adata.var_names = ["Gene1", "Gene2", "MT-Gene3"]
    input_path = tmp_path / "sample.h5ad"
    output_path = tmp_path / "assessment.md"
    adata.write_h5ad(input_path)

    result = assess_qc(input_path, output_path)

    assert result["assessment"] == "not_assessable"
    assert result["selected_batch_field"] is None
    assert output_path.exists()
    assert "不能可靠判断批次效应" in output_path.read_text()


def test_report_compares_batch_metrics(tmp_path: Path) -> None:
    adata = ad.AnnData(np.ones((6, 3)))
    adata.var_names = ["Gene1", "Gene2", "MT-Gene3"]
    adata.obs["batch"] = ["A", "A", "A", "B", "B", "B"]
    input_path = tmp_path / "batched.h5ad"
    output_path = tmp_path / "assessment.md"
    adata.write_h5ad(input_path)

    result = assess_qc(input_path, output_path)

    assert result["assessment"] == "assessed"
    assert set(result["per_batch"]) == {"A", "B"}
