# bio-lab
bio experience analysis platform

## 本地启动 Streamlit

```bash
uv sync --dev
uv run streamlit run app/app.py
```

打开终端提示的本地地址，上传 `.h5ad` 后点击“运行 QC”。应用会为每次运行创建独立的 `output/streamlit_runs/<job_id>/` 目录，依次执行 Scanpy QC 和本地 `omics-scientist` QC 评估，并在页面展示图表与报告下载入口。

## 部署说明

仓库包含 `requirements.txt`，可用于 Streamlit Community Cloud 等从 GitHub 构建的部署环境。部署入口设置为 `app/app.py`。当前版本使用进程内执行，适合原型和单用户任务；生产环境应将 `execute_qc_job` 移到 FastAPI/Worker，并用任务队列和持久化对象存储承载长任务与结果。
