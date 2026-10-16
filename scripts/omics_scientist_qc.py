"""Local omics-scientist-style QC and batch-effect assessment."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import anndata as ad
import numpy as np
import scanpy as sc


BATCH_FIELD_HINTS = ("batch", "sample", "donor", "library", "replicate", "lane")


def _find_batch_fields(adata: ad.AnnData) -> list[str]:
    return [
        column
        for column in adata.obs.columns
        if any(hint in column.lower() for hint in BATCH_FIELD_HINTS)
        and adata.obs[column].nunique(dropna=True) > 1
    ]


def assess_qc(input_path: str | Path, output_path: str | Path) -> dict[str, object]:
    """Assess QC and possible batch effects without modifying the input file."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    adata = ad.read_h5ad(input_path)

    adata.var["mt"] = adata.var_names.str.upper().str.startswith("MT-")
    sc.pp.calculate_qc_metrics(
        adata, qc_vars=["mt"], percent_top=None, inplace=True, log1p=False
    )
    qc_pass = (
        (adata.obs["n_genes_by_counts"] >= 200)
        & (adata.obs["pct_counts_mt"] <= 20)
    )
    batch_fields = _find_batch_fields(adata)
    selected_batch = batch_fields[0] if batch_fields else None
    per_batch: dict[str, dict[str, float | int]] = {}
    if selected_batch:
        for batch, group in adata.obs.groupby(selected_batch, observed=True):
            per_batch[str(batch)] = {
                "cells": int(len(group)),
                "median_genes": float(group["n_genes_by_counts"].median()),
                "median_mito_pct": float(group["pct_counts_mt"].median()),
                "qc_pass_fraction": float(qc_pass.loc[group.index].mean()),
            }

    assessment = "not_assessable" if selected_batch is None else "assessed"
    recommendations = []
    if selected_batch is None:
        recommendations.extend(
            [
                "未发现批次元数据，当前不能可靠判断批次效应。请在 adata.obs 中提供 batch/sample/donor/library 等字段。",
                "补充批次字段后，重新运行本评估器并比较各批次 QC 指标及下游聚类结构。",
            ]
        )
    else:
        mito_values = [item["median_mito_pct"] for item in per_batch.values()]
        pass_values = [item["qc_pass_fraction"] for item in per_batch.values()]
        if max(mito_values) - min(mito_values) > 5:
            recommendations.append("批次间中位线粒体比例差异超过 5 个百分点，建议检查样本质量和实验流程。")
        if max(pass_values) - min(pass_values) > 0.15:
            recommendations.append("批次间 QC 通过率差异超过 15 个百分点，建议进行批次敏感性分析。")
        if not recommendations:
            recommendations.append("未发现基于当前 QC 指标的明显批次差异；仍需在标准化和聚类后复核。")

    result = {
        "input": str(input_path),
        "assessment": assessment,
        "batch_fields_found": batch_fields,
        "selected_batch_field": selected_batch,
        "overall": {
            "cells": int(adata.n_obs),
            "qc_pass_fraction": float(np.mean(qc_pass)),
            "median_genes": float(adata.obs["n_genes_by_counts"].median()),
            "median_mito_pct": float(adata.obs["pct_counts_mt"].median()),
        },
        "per_batch": per_batch,
        "recommendations": recommendations,
    }
    output_path.with_suffix(".json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    output_path.write_text(_render_report(result), encoding="utf-8")
    return result


def _render_report(result: dict[str, object]) -> str:
    overall = result["overall"]
    lines = [
        "# omics-scientist QC 评估报告",
        "",
        f"- 输入：`{result['input']}`",
        f"- 评估状态：`{result['assessment']}`",
        f"- 细胞数：{overall['cells']}",
        f"- QC 通过比例：{overall['qc_pass_fraction']:.1%}",
        f"- 中位检测基因数：{overall['median_genes']:.1f}",
        f"- 中位线粒体比例：{overall['median_mito_pct']:.2f}%",
        "",
        "## 批次字段",
        "",
        f"发现字段：{', '.join(result['batch_fields_found']) or '无'}",
        "",
    ]
    if result["per_batch"]:
        lines.extend(["## 各批次 QC 指标", "", "| 批次 | 细胞数 | 中位检测基因数 | 中位线粒体比例 | QC 通过比例 |", "|---|---:|---:|---:|---:|"])
        for batch, metrics in result["per_batch"].items():
            lines.append(f"| {batch} | {metrics['cells']} | {metrics['median_genes']:.1f} | {metrics['median_mito_pct']:.2f}% | {metrics['qc_pass_fraction']:.1%} |")
    lines.extend(["", "## 下一步建议", ""])
    lines.extend(f"- {recommendation}" for recommendation in result["recommendations"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Input .h5ad file")
    parser.add_argument("output", help="Markdown report path")
    args = parser.parse_args()
    print(assess_qc(args.input, args.output))


if __name__ == "__main__":
    main()
