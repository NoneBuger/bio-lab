"""Streamlit control panel for the local QC pipeline."""

from pathlib import Path

import anndata as ad
import streamlit as st

# Streamlit places the entry script's directory on sys.path, so import the
# sibling module directly. This avoids `app.py` shadowing the `app` package.
from pipeline import execute_qc_job


st.set_page_config(page_title="Bio Lab", page_icon="🧬", layout="wide")
st.title("🧬 细胞生物学 AI 分析平台")
st.caption("当前版本：上传 AnnData → Scanpy QC → omics-scientist QC 评估")

uploaded = st.file_uploader("上传单细胞数据（.h5ad）", type=["h5ad"], key="dataset_uploader")
if uploaded is not None:
    try:
        # UploadedFile is file-like; use an in-memory preview here. The
        # analysis job itself writes the bytes to a temporary .h5ad file.
        preview = ad.read_h5ad(uploaded)
        st.info(f"数据预览：{preview.n_obs:,} 个细胞 × {preview.n_vars:,} 个基因")
    except Exception as exc:
        st.error(f"无法读取 AnnData 文件：{exc}")
        st.stop()

with st.sidebar:
    st.header("QC 参数")
    min_genes = st.number_input("细胞最少检测基因数", min_value=0, value=200, step=10, key="min_genes")
    min_cells = st.number_input("基因最少出现细胞数", min_value=1, value=3, step=1, key="min_cells")
    max_mito_pct = st.number_input("最大线粒体比例 (%)", min_value=0.0, value=20.0, step=1.0, key="max_mito_pct")

instruction = st.text_area(
    "分析指令（当前用于记录，Agent 编排将在后续版本接入）",
    value="完成基础单细胞 QC 并评估批次效应",
    key="analysis_instruction",
)

if st.button("运行 QC", type="primary", disabled=uploaded is None, key="run_qc"):
    with st.spinner("正在执行 Scanpy QC 和 QC 评估…"):
        try:
            result = execute_qc_job(
                uploaded.getvalue(),
                Path("output") / "streamlit_runs",
                min_genes=int(min_genes),
                min_cells=int(min_cells),
                max_mito_pct=float(max_mito_pct),
            )
            st.session_state["last_result"] = result
            st.session_state["last_instruction"] = instruction
        except Exception as exc:
            st.exception(exc)

result = st.session_state.get("last_result")
if result:
    summary = result["summary"]
    assessment = result["assessment"]
    st.success(f"任务 {result['job_id']} 完成")
    columns = st.columns(4)
    columns[0].metric("输入细胞", summary["before"]["cells"])
    columns[1].metric("输出细胞", summary["after"]["cells"])
    columns[2].metric("输入基因", summary["before"]["genes"])
    columns[3].metric("输出基因", summary["after"]["genes"])

    st.subheader("QC 图表")
    qc_dir = Path(result["output_dir"]) / "qc"
    chart_columns = st.columns(2)
    chart_columns[0].image(str(qc_dir / "qc_before.png"), caption="QC 前 violin plot")
    chart_columns[1].image(str(qc_dir / "qc_after.png"), caption="QC 后 violin plot")
    chart_columns = st.columns(2)
    chart_columns[0].image(str(qc_dir / "qc_before_scatter.png"), caption="QC 前 scatter plot")
    chart_columns[1].image(str(qc_dir / "qc_after_scatter.png"), caption="QC 后 scatter plot")

    st.subheader("omics-scientist 评估")
    st.json(assessment)
    report_path = Path(result["output_dir"]) / "omics_scientist" / "qc_assessment.md"
    st.download_button(
        "下载 QC 评估报告",
        report_path.read_text(encoding="utf-8"),
        file_name=f"{result['job_id']}_qc_assessment.md",
        mime="text/markdown",
    )
