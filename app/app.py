"""Streamlit research cockpit for asynchronous multi-agent analysis."""

from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st

try:
    from api_client import BioLabAPIError, get_task_artifact, poll_task, submit_task
except ModuleNotFoundError:
    from app.api_client import BioLabAPIError, get_task_artifact, poll_task, submit_task


STAGE_LABELS = {
    "PENDING": "任务排队中",
    "RECEIVED": "任务已进入分析队列",
    "EXTRACTING_ENTITIES": "正在提取文献检索实体",
    "AI_GENERATING_CODE": "AI 正在生成分析代码",
    "EXECUTING_ANALYSIS": "正在执行 QC 分析",
    "ASSESSING_BATCH_EFFECT": "正在评估批次效应",
    "SEARCHING_LITERATURE": "正在检索文献",
    "SUMMARIZING_LITERATURE": "正在生成文献摘要",
    "FINALIZING": "正在整理分析结果",
    "SUCCESS": "分析完成",
    "FAILURE": "分析失败",
}

TASK_TYPES = {
    "自动判断": "auto",
    "仅数据分析": "data_analyst",
    "仅文献检索": "literature",
    "综合分析": "hybrid",
}


def _error_message(error: str) -> str:
    text = error or "未知错误"
    if "OPENAI_API_KEY" in text:
        return "未配置 OpenAI API Key，请在环境中设置后重试。下一步建议：配置 OPENAI_API_KEY 后重新提交。"
    if "Europe PMC" in text or "literature" in text.lower() and "unavailable" in text.lower():
        return "文献数据库暂时不可访问，请稍后重试。下一步建议：稍后重新提交文献任务。"
    if "no_results" in text.lower() or "No papers" in text:
        return "未找到匹配文献，请尝试调整基因名、细胞类型或疾病关键词。下一步建议：补充更具体的检索实体。"
    if "安全沙盒拦截" in text or "sandbox" in text.lower():
        return "AI 生成的代码触发了安全沙盒拦截，请简化指令后重试。下一步建议：仅请求基础 QC 和批次效应评估。"
    if "h5ad" in text.lower() or "required" in text.lower():
        return "当前任务类型需要上传 .h5ad 文件。下一步建议：上传有效的 .h5ad 文件后重试。"
    return f"任务执行失败：{text}。下一步建议：检查指令和数据规模后重试。"


def _artifact(base_url: str, task_id: str, name: str) -> bytes | None:
    try:
        return get_task_artifact(base_url, task_id, name)
    except Exception as exc:  # noqa: BLE001 - artifact errors should not hide other results.
        st.warning(f"无法加载结果文件 {name}：{exc}。下一步建议：检查后端服务后重试下载。")
        return None


def _show_analysis(base_url: str, task_id: str, result: dict[str, Any], agent_type: str) -> None:
    if agent_type == "literature":
        st.info("本次任务为文献检索，无数据分析结果。")
        return
    qc = result.get("qc", result)
    summary = qc.get("summary", {})
    assessment = qc.get("assessment", {})
    before, after = summary.get("before", {}), summary.get("after", {})
    columns = st.columns(4)
    columns[0].metric("输入细胞", before.get("cells", "—"))
    columns[1].metric("输出细胞", after.get("cells", "—"))
    columns[2].metric("输入基因", before.get("genes", "—"))
    columns[3].metric("输出基因", after.get("genes", "—"))

    st.subheader("QC 图表")
    chart_columns = st.columns(2)
    for column, name, caption in [
        (chart_columns[0], "qc_before", "QC 前 violin plot"),
        (chart_columns[1], "qc_after", "QC 后 violin plot"),
    ]:
        image = _artifact(base_url, task_id, name)
        if image:
            column.image(image, caption=caption)
    chart_columns = st.columns(2)
    for column, name, caption in [
        (chart_columns[0], "qc_before_scatter", "QC 前 scatter plot"),
        (chart_columns[1], "qc_after_scatter", "QC 后 scatter plot"),
    ]:
        image = _artifact(base_url, task_id, name)
        if image:
            column.image(image, caption=caption)

    st.subheader("批次效应评估")
    st.json(assessment)
    for name, label in [("qc_report", "下载 QC 报告"), ("assessment_report", "下载批次效应评估")]:
        report = _artifact(base_url, task_id, name)
        if report:
            st.download_button(label, report, file_name=f"{task_id}_{name}.md", mime="text/markdown", key=f"download_{name}")


def _show_literature(base_url: str, task_id: str, result: dict[str, Any], agent_type: str) -> None:
    if agent_type == "data_analyst":
        st.info("本次任务为数据分析，未执行文献检索。")
        return
    literature = result.get("literature", result)
    queries = literature.get("queries", [])
    st.subheader("检索方向")
    for query in queries:
        st.markdown(f"- `{query}`")
    for paper in literature.get("papers", []):
        with st.container(border=True):
            st.markdown(f"### {paper.get('title', 'Untitled')}")
            st.write(f"作者：{paper.get('authors') or '不可用'}")
            st.write(f"期刊/年份：{paper.get('journal') or '不可用'} / {paper.get('year') or '不可用'}")
            st.write(f"PMID：{paper.get('pmid') or '不可用'}；DOI：{paper.get('doi') or '不可用'}")
            if paper.get("url"):
                st.markdown(f"[Europe PMC 链接]({paper['url']})")
            st.json(paper.get("summary", {}))
    report = _artifact(base_url, task_id, "literature_report")
    if report:
        st.download_button("下载 literature_report.md", report, file_name=f"{task_id}_literature_report.md", mime="text/markdown", key="download_literature")


st.set_page_config(page_title="Bio Lab", page_icon="🧬", layout="wide")
st.title("🧬 细胞生物学 AI 分析平台")
st.caption("自然语言指令 → FastAPI → Celery/Redis → Scanpy / Literature Agent")

backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
st.sidebar.text_input("后端 API 地址", value=backend_url, key="backend_url")
with st.sidebar:
    st.header("任务设置")
    task_label = st.selectbox("任务类型", list(TASK_TYPES), key="task_type_label")
    agent_type = TASK_TYPES[task_label]
    st.header("QC 参数")
    min_genes = st.number_input("细胞最少检测基因数", min_value=0, value=200, step=10)
    min_cells = st.number_input("基因最少出现细胞数", min_value=1, value=3, step=1)
    max_mito_pct = st.number_input("最大线粒体比例 (%)", min_value=0.0, value=20.0, step=1.0)

if agent_type == "literature":
    uploaded = None
    st.info("文献检索无需上传数据文件。")
else:
    uploaded = st.file_uploader("上传单细胞数据（.h5ad，必需）", type=["h5ad"], key="dataset_uploader")
    if agent_type == "auto":
        st.caption("自动判断默认按数据分析处理；若只需文献检索，请选择“仅文献检索”。")
    if uploaded is not None:
        st.info(f"已选择：{uploaded.name}（{uploaded.size / 1024**2:.1f} MB）")

instruction = st.text_area(
    "分析指令",
    value=st.session_state.get("analysis_instruction", "完成基础单细胞 QC 并评估批次效应"),
    key="analysis_instruction",
)

max_size_gb = float(os.getenv("MAX_UPLOAD_SIZE_GB", "5"))
max_size_bytes = max_size_gb * 1024**3
file_too_large = bool(uploaded and uploaded.size > max_size_bytes)
if file_too_large:
    st.error(f"文件超过 {max_size_gb:g}GB，请先降采样后重试。下一步建议：压缩或降采样后重新上传。")

requires_file = agent_type != "literature"
submit_disabled = (requires_file and uploaded is None) or file_too_large
if st.button("提交分析任务", type="primary", disabled=submit_disabled, key="submit_task"):
    try:
        response = submit_task(
            st.session_state.backend_url,
            agent_type=agent_type,
            file_bytes=uploaded.getvalue() if uploaded else None,
            filename=uploaded.name if uploaded else None,
            instruction=instruction,
            min_genes=int(min_genes),
            min_cells=int(min_cells),
            max_mito_pct=float(max_mito_pct),
        )
        st.session_state["task_id"] = response["task_id"]
        st.session_state["task_agent_type"] = agent_type
        st.session_state["route_info"] = {
            "agent_type": agent_type,
            "reasoning": "由用户选择" if agent_type != "auto" else "由后端路由器自动判断",
        }
        st.session_state["submitted_at"] = time.time()
        st.session_state.pop("task_result", None)
        st.rerun()
    except Exception as exc:
        st.error(f"提交任务失败：{_error_message(str(exc))}")

task_id = st.session_state.get("task_id")
if task_id and "task_result" not in st.session_state:
    progress = st.progress(0, text="任务排队中（0%）")
    status_box = st.empty()
    started_at = st.session_state.get("submitted_at", time.time())

    def render_status(status: dict[str, Any]) -> None:
        current = int(status.get("progress", 0))
        stage = status.get("stage") or status.get("status", "PENDING")
        elapsed = int(max(0, time.time() - started_at))
        progress.progress(current, text=f"{STAGE_LABELS.get(stage, stage)}（{current}%）")
        status_box.info(f"{STAGE_LABELS.get(stage, stage)} · {current}% · 已耗时 {elapsed} 秒")

    try:
        final_status = poll_task(
            st.session_state.backend_url,
            task_id,
            on_status=render_status,
            timeout_minutes=float(os.getenv("POLL_TIMEOUT_MINUTES", "30")),
        )
        if final_status.get("status") == "SUCCESS":
            st.session_state["task_result"] = final_status.get("result", {})
            st.rerun()
        else:
            status_box.error(_error_message(final_status.get("error", final_status.get("message", "任务失败"))))
    except TimeoutError:
        status_box.error("任务执行超时，请检查数据规模或联系管理员。下一步建议：缩小数据规模后重试。")
    except (BioLabAPIError, Exception) as exc:
        status_box.error(f"查询任务失败：{_error_message(str(exc))}")

result = st.session_state.get("task_result")
if result and task_id:
    selected_agent = st.session_state.get("task_agent_type", "auto")
    if selected_agent == "auto":
        selected_agent = "hybrid" if "literature" in result else "data_analyst"
    st.success(f"任务 {task_id} 完成")
    analysis_tab, literature_tab, raw_tab = st.tabs(["分析结果", "文献综述", "原始输出"])
    with analysis_tab:
        _show_analysis(st.session_state.backend_url, task_id, result, selected_agent)
    with literature_tab:
        _show_literature(st.session_state.backend_url, task_id, result, selected_agent)
    with raw_tab:
        st.subheader("路由决策")
        st.json(st.session_state.get("route_info", {"agent_type": selected_agent}))
        generated_code = result.get("generated_code") or result.get("qc", {}).get("generated_code")
        if generated_code:
            st.subheader("Agent 生成代码")
            st.code(generated_code, language="python")
        provenance = _artifact(st.session_state.backend_url, task_id, "provenance")
        if provenance:
            st.download_button("下载 provenance.json", provenance, file_name=f"{task_id}_provenance.json", mime="application/json", key="download_provenance")
        st.subheader("原始 JSON 结果")
        st.json(result)
