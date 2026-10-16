"""Minimal Streamlit front end for uploading single-cell data."""

import streamlit as st


def placeholder_analysis(instruction: str) -> str:
    return f"已收到分析指令（占位）：{instruction or '未输入指令'}"


st.set_page_config(page_title="Bio Lab", page_icon="🧬")
st.title("细胞生物学 AI 分析平台")
uploaded = st.file_uploader("上传单细胞数据（.h5ad）", type=["h5ad"])
if uploaded is not None:
    import anndata as ad

    adata = ad.read_h5ad(uploaded)
    st.metric("细胞数", adata.n_obs)
    st.metric("基因数", adata.n_vars)

instruction = st.text_area("向分析引擎发送指令")
if st.button("提交"):
    st.info(placeholder_analysis(instruction))
