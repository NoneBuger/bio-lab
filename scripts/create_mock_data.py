"""Create a deterministic toy .h5ad dataset for smoke testing."""

from pathlib import Path

import anndata as ad
import numpy as np
from scipy import sparse


def create_mock_data(output_path: str | Path, seed: int = 7) -> Path:
    rng = np.random.default_rng(seed)
    n_cells, n_genes = 120, 300
    gene_names = np.array([f"Gene{i:03d}" for i in range(n_genes)], dtype=object)
    gene_names[:15] = [f"MT-GENE{i:02d}" for i in range(15)]
    counts = rng.poisson(lam=1.2, size=(n_cells, n_genes)).astype(np.int32)
    counts[:, :15] = rng.poisson(lam=0.08, size=(n_cells, 15)).astype(np.int32)
    counts[:8, :] = rng.binomial(counts[:8, :], 0.05).astype(np.int32)
    counts[8:14, :15] += rng.poisson(lam=18, size=(6, 15)).astype(np.int32)
    counts[:, -10:] = 0
    counts[0, -10:] = 1

    adata = ad.AnnData(X=sparse.csr_matrix(counts))
    adata.var_names = gene_names
    adata.obs_names = [f"mock_cell_{i:03d}" for i in range(n_cells)]
    adata.uns["mock_data"] = {"seed": seed, "purpose": "QC smoke test"}
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    adata.write_h5ad(output_path)
    return output_path


if __name__ == "__main__":
    create_mock_data("data/mock.h5ad")
