"""Reproducible basic single-cell QC workflow."""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import matplotlib.pyplot as plt
import scanpy as sc


def run_qc(
    input_path: str | Path,
    output_dir: str | Path,
    *,
    min_genes: int = 200,
    min_cells: int = 3,
    max_mito_pct: float = 20.0,
) -> dict[str, object]:
    """Run basic QC and write plots, report, and provenance metadata."""
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    adata = sc.read_h5ad(input_path)
    before = {"cells": int(adata.n_obs), "genes": int(adata.n_vars)}

    adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
    # Avoid Scanpy's default top-500 metrics: small smoke-test datasets may
    # legitimately contain fewer than 500 genes.
    sc.pp.calculate_qc_metrics(
        adata, qc_vars=["mt"], percent_top=None, inplace=True, log1p=False
    )

    sc.pl.violin(
        adata,
        ["n_genes_by_counts", "total_counts", "pct_counts_mt"],
        multi_panel=True,
        show=False,
    )
    plt.savefig(output_dir / "qc_before.png", dpi=140, bbox_inches="tight")
    plt.close("all")

    sc.pp.filter_genes(adata, min_cells=min_cells)
    sc.pp.filter_cells(adata, min_genes=min_genes)
    adata = adata[adata.obs["pct_counts_mt"] <= max_mito_pct].copy()
    after = {"cells": int(adata.n_obs), "genes": int(adata.n_vars)}

    sc.pl.violin(
        adata,
        ["n_genes_by_counts", "total_counts", "pct_counts_mt"],
        multi_panel=True,
        show=False,
    )
    plt.savefig(output_dir / "qc_after.png", dpi=140, bbox_inches="tight")
    plt.close("all")

    summary = {
        "input": str(input_path),
        "before": before,
        "after": after,
        "removed": {
            "cells": before["cells"] - after["cells"],
            "genes": before["genes"] - after["genes"],
        },
        "filters": {
            "min_genes": min_genes,
            "min_cells": min_cells,
            "max_mito_pct": max_mito_pct,
        },
    }
    (output_dir / "qc_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    provenance = {
        "created_at_utc": datetime.now(UTC).isoformat(),
        "python": platform.python_version(),
        "scanpy": version("scanpy"),
        "input": str(input_path),
        "workflow": "basic_qc",
        "parameters": summary["filters"],
    }
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2), encoding="utf-8"
    )
    (output_dir / "qc_report.md").write_text(
        "# 单细胞 QC 报告\n\n"
        f"- 输入细胞数：{before['cells']}\n"
        f"- 输入基因数：{before['genes']}\n"
        f"- 输出细胞数：{after['cells']}\n"
        f"- 输出基因数：{after['genes']}\n"
        f"- 过滤参数：min_genes >= {min_genes}，min_cells >= {min_cells}，"
        f"线粒体比例 <= {max_mito_pct}%\n\n"
        "图表：`qc_before.png`、`qc_after.png`。\n\n"
        "运行元数据见 `provenance.json`。\n",
        encoding="utf-8",
    )
    return summary
