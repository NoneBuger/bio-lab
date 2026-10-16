# bio-lab
bio experience analysis platform

## 本地启动 Streamlit

```bash
uv sync --dev
uv run streamlit run app/app.py
```

打开终端提示的本地地址，上传 `.h5ad` 后点击“提交异步 QC 任务”。Streamlit 会调用 FastAPI，后端把任务交给 Celery/Redis，前端轮询任务状态并在完成后展示图表与报告下载入口。

## 部署说明

仓库包含 `requirements.txt`，可用于从 GitHub 构建的部署环境。部署入口设置为 `app/app.py`。Streamlit 前端通过 `BACKEND_URL` 连接 FastAPI；FastAPI、Celery worker、Redis 和结果存储需要部署在彼此可访问的环境中。

## 本地四进程启动

先安装依赖：

```bash
uv sync --dev
```

### Linux/macOS

终端 1，启动 Redis：

```bash
docker run --name bio-lab-redis -p 6379:6379 -d redis:7-alpine
```

终端 2，启动 FastAPI：

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

终端 3，启动 Celery worker：

```bash
uv run celery -A backend.celery_app.celery_app worker --loglevel=info --concurrency=1
```

终端 4，启动 Streamlit：

```bash
BACKEND_URL=http://localhost:8000 uv run streamlit run app/app.py
```

### Windows PowerShell

Redis 推荐使用 Docker Desktop：

```powershell
docker run --name bio-lab-redis -p 6379:6379 -d redis:7-alpine
```

终端 2：

```powershell
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

终端 3 使用 Celery solo pool：

```powershell
uv run celery -A backend.celery_app.celery_app worker --loglevel=info --pool=solo
```

终端 4：

```powershell
$env:BACKEND_URL="http://localhost:8000"
uv run streamlit run app/app.py
```

FastAPI 文档地址：<http://localhost:8000/docs>。健康检查：<http://localhost:8000/health>。

### 没有 Redis/Docker 时运行测试

测试会使用 Celery eager 模式，不需要 Redis：

```bash
CELERY_TASK_ALWAYS_EAGER=true uv run pytest -q
```

该模式只适合测试，不适合大文件生产任务。真实异步运行时，取消这个环境变量并启动 Redis 和 Celery worker。

### 关键环境变量

```text
BACKEND_URL=http://localhost:8000
REDIS_URL=redis://localhost:6379
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
BIO_LAB_JOB_DIR=output/jobs
MAX_UPLOAD_SIZE_GB=5
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4.1-mini
```

API 接收上传文件后先写入 `BIO_LAB_JOB_DIR/<task_id>/input/`，Celery worker 读取同一共享路径并写入 QC artifacts。多容器部署时需要把该目录换成共享卷或对象存储。

使用 Docker Compose 时，可在项目根目录创建未提交的 `.env` 文件，Compose 会将其中的 `OPENAI_API_KEY` 和 `OPENAI_MODEL` 注入 API 与 worker。不要把 `.env` 或 API Key 提交到 Git。

## Docker Compose 一键启动

任务一的 Docker Compose 配置会启动 Redis、FastAPI API 和 Celery worker，并将 `output/jobs/` 挂载为 API/worker 共享目录：

```bash
docker compose up --build
```

后台启动：

```bash
docker compose up --build -d
```

查看服务日志：

```bash
docker compose logs -f api worker redis
```

停止服务：

```bash
docker compose down
```

如果在本地不使用 Docker 跑 Streamlit，请确保 `BACKEND_URL` 设置为 `http://localhost:8000`；如果在云端或容器网络内跑，请改为对应的服务地址。

Compose 网络内的 Streamlit 如果作为额外容器运行，应使用 `BACKEND_URL=http://api:8000`；浏览器访问宿主机上的 Streamlit 时，则使用宿主机可访问的 API 地址。
