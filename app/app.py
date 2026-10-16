"""Streamlit frontend for the asynchronous FastAPI/Celery QC pipeline."""

import os
import time

import streamlit as st

try:
    from api_client import get_artifact, get_qc_status, submit_qc
except ModuleNotFoundError:
    from app.api_client import get_artifact, get_qc_status, submit_qc


st.set_page_config(page_title="Bio Lab", page_icon="🧬", layout="wide")
st.title("🧬 细胞生物学 AI 分析平台")
st.caption("上传 AnnData → FastAPI → Celery/Redis → Scanpy QC")

backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
st.sidebar.text_input("后端 API 地址", value=backend_url, key="backend_url")
with st.sidebar:
    st.header("QC 参数")
    min_genes = st.number_input("细胞最少检测基因数", min_value=0, value=200, step=10)
    min_cells = st.number_input("基因最少出现细胞数", min_value=1, value=3, step=1)
    max_mito_pct = st.number_input("最大线粒体比例 (%)", min_value=0.0, value=20.0, step=1.0)

uploaded = st.file_uploader("上传单细胞数据（.h5ad）", type=["h5ad"], key="dataset_uploader")
if uploaded is not None:
    st.info(f"已选择：{uploaded.name}（{uploaded.size / 1024**2:.1f} MB）")

instruction = st.text_area(
    "分析指令",
    value="完成基础单细胞 QC 并评估批次效应",
    key="analysis_instruction",
)

if st.button("提交异步 QC 任务", type="primary", disabled=uploaded is None, key="submit_qc"):
    try:
        response = submit_qc(
            st.session_state.backend_url,
            uploaded.getvalue(),
            uploaded.name,
            instruction,
            int(min_genes),
            int(min_cells),
            float(max_mito_pct),
        )
        st.session_state["task_id"] = response["task_id"]
        st.session_state.pop("task_result", None)
    except Exception as exc:
        st.error(f"提交任务失败：{exc}")

task_id = st.session_state.get("task_id")
if task_id and "task_result" not in st.session_state:
    progress = st.progress(0, text=f"任务 {task_id}：等待 worker…")
    status_box = st.empty()
    try:
        while True:
            status = get_qc_status(st.session_state.backend_url, task_id)
            current = int(status.get("progress", 0))
            progress.progress(current, text=f"{status.get('stage') or status['status']}：{status.get('message') or ''}")
            if status["status"] == "SUCCESS":
                st.session_state["task_result"] = status["result"]
                break
            if status["status"] == "FAILURE":
                status_box.error(f"任务失败：{status.get('error', 'unknown error')}")
                break
            status_box.info(f"任务状态：{status['status']}，进度 {current}%")
            time.sleep(2)
    except Exception as exc:
        status_box.error(f"查询任务失败：{exc}")

result = st.session_state.get("task_result")
if result:
    summary = result["summary"]
    assessment = result["assessment"]
    st.success(f"任务 {result['task_id']} 完成")
    columns = st.columns(4)
    columns[0].metric("输入细胞", summary["before"]["cells"])
    columns[1].metric("输出细胞", summary["after"]["cells"])
    columns[2].metric("输入基因", summary["before"]["genes"])
    columns[3].metric("输出基因", summary["after"]["genes"])

    st.subheader("QC 图表")
    chart_columns = st.columns(2)
    for column, name, caption in [
        (chart_columns[0], "qc_before", "QC 前 violin plot"),
        (chart_columns[1], "qc_after", "QC 后 violin plot"),
    ]:
        column.image(get_artifact(st.session_state.backend_url, task_id, name), caption=caption)
    chart_columns = st.columns(2)
    for column, name, caption in [
        (chart_columns[0], "qc_before_scatter", "QC 前 scatter plot"),
        (chart_columns[1], "qc_after_scatter", "QC 后 scatter plot"),
    ]:
        column.image(get_artifact(st.session_state.backend_url, task_id, name), caption=caption)

    st.subheader("omics-scientist 评估")
    st.json(assessment)
    report = get_artifact(st.session_state.backend_url, task_id, "assessment_report")
    st.download_button(
        "下载 QC 评估报告", report, file_name=f"{task_id}_qc_assessment.md", mime="text/markdown"
    )
