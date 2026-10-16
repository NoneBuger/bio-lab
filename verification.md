# Bio Lab 端到端 Smoke Test 验证指南

本文假设读者第一次接触本项目。验证分为四个阶段：先用本地 eager 模式确认代码链路，再用 Docker Compose 验证真实 Redis/Celery，最后连接 Streamlit 和真实 `.h5ad` 数据。

## 0. 环境变量清单

| 变量 | 默认值 | 必需 | 使用层级 | 敏感 | 示例/说明 |
|---|---|---:|---|---:|---|
| `OPENAI_API_KEY` | 无 | 是（AI 代码生成或有摘要文献任务） | 通用 / Celery | 是 | `sk-your-key-here` |
| `OPENAI_MODEL` | `gpt-4.1-mini` | 否 | Celery | 否 | 代码生成模型 |
| `OPENAI_MODEL_ROUTER` | `OPENAI_MODEL`，否则 `gpt-4.1-mini` | 否 | Celery | 否 | 路由和实体提取模型 |
| `OPENAI_MODEL_SUMMARY` | `OPENAI_MODEL`，否则 `gpt-4.1-mini` | 否 | Celery | 否 | 文献摘要模型 |
| `REDIS_URL` | `redis://localhost:6379` | 真实异步时是 | Celery | 否 | 本地 Redis 地址 |
| `CELERY_BROKER_URL` | 由 `REDIS_URL` 推导 `/0` | 否 | Celery | 否 | 设置后覆盖 broker 地址 |
| `CELERY_RESULT_BACKEND` | 由 `REDIS_URL` 推导 `/1` | 否 | Celery | 否 | 设置后覆盖结果 backend |
| `CELERY_TASK_ALWAYS_EAGER` | `false` | 否 | Celery | 否 | `true` 时本地同步执行，不需要 Redis |
| `BIO_LAB_JOB_DIR` | `output/jobs` | 否 | FastAPI / Celery | 否 | Docker 中为 `/app/output/jobs` |
| `MAX_UPLOAD_BYTES` | `4294967296`（4 GiB） | 否 | FastAPI | 否 | 后端上传限制 |
| `EUROPE_PMC_URL` | `https://www.ebi.ac.uk/europepmc/webservices/rest/search` | 否 | Celery | 否 | 文献 API，可替换为测试 mock 端点 |
| `LITERATURE_YEARS` | `5` | 否 | Celery | 否 | 文献回溯年数 |
| `LITERATURE_MAX_RESULTS` | `10` | 否 | Celery | 否 | 文献最大返回数 |
| `BACKEND_URL` | `http://localhost:8000` | 否 | Streamlit | 否 | Streamlit 访问 FastAPI 的地址 |
| `MAX_UPLOAD_SIZE_GB` | `5` | 否 | Streamlit | 否 | 前端上传限制 |
| `POLL_TIMEOUT_MINUTES` | `30` | 否 | Streamlit | 否 | 前端轮询超时 |
| `AGENT_MAX_CODE_LENGTH` | 无读取点 | 否 | 未实现 | 否 | 当前沙盒尚未使用 |
| `AGENT_EXECUTION_TIMEOUT` | 无读取点 | 否 | 未实现 | 否 | 当前沙盒尚未使用 |

`OPENAI_API_KEY` 只应放在本地未提交的 `.env`、部署平台 Secret 或运行环境中。不要把真实 Key 写入 YAML、README 或镜像。

## 已发现的问题清单

这些问题本次只记录，没有修改业务代码：

1. Streamlit 默认限制为 5 GB（`MAX_UPLOAD_SIZE_GB`），FastAPI 默认限制为 4 GiB（`MAX_UPLOAD_BYTES`），存在前后端边界不一致。
2. `AGENT_MAX_CODE_LENGTH` 与 `AGENT_EXECUTION_TIMEOUT` 尚未被 `backend/sandbox.py` 或其他代码读取，不能宣称它们已经提供运行时限制。
3. `docker-compose.yml` 只显式传递 `OPENAI_API_KEY`、`OPENAI_MODEL`；`OPENAI_MODEL_ROUTER`、`OPENAI_MODEL_SUMMARY`、`EUROPE_PMC_URL`、`LITERATURE_YEARS` 和 `LITERATURE_MAX_RESULTS` 不会从 `.env` 自动进入容器。
4. `.dockerignore` 当前忽略 `.env` 和 `.env.*`；但 `.gitignore` 当前没有忽略 `.env`，这是敏感文件保护遗漏，应在后续配置修复中补上。`.env.example` 当前未被 Git 忽略，可以提交模板。

## 1. 环境准备

### 1.1 获取代码和依赖

```bash
git clone https://github.com/NoneBuger/bio-lab.git
cd bio-lab
uv sync --dev
cp .env.example .env
```

编辑 `.env`，至少在需要真实 AI 分析时填入 `OPENAI_API_KEY`。纯代码测试可以保留占位符。

确认 Python 和 Scanpy：

```bash
uv run python --version
uv run python -c "import scanpy; print(scanpy.__version__)"
```

预期输出：Python 3.12 或更高版本，以及一个 Scanpy 版本号。

判断 Docker/Redis 是否可用：

```bash
docker version
docker compose version
redis-cli ping
```

`docker version` 和 `docker compose version` 成功表示可进行阶段二；`redis-cli ping` 返回 `PONG` 表示本地 Redis 可用。Docker 不可用也不阻碍阶段一。

## 2. 阶段一：无 Redis 的 eager 模式

这是最低门槛验证，不需要 Docker 或 Redis：

```bash
CELERY_TASK_ALWAYS_EAGER=true \
UV_CACHE_DIR=/tmp/bio-lab-uv-cache \
uv run --no-sync python -m pytest -q
```

预期输出：所有测试通过，例如 `47 passed`。

生成最小 smoke-test 数据：

```bash
uv run python scripts/create_mock_data.py
```

预期文件：`data/mock.h5ad`。该数据约 120 个细胞、300 个基因，包含线粒体基因和可触发 QC 过滤的细胞，适合验证流程，不代表真实生物学结论。

如果失败：

- `ModuleNotFoundError`：运行 `uv sync --dev`。
- uv cache 只读：设置 `UV_CACHE_DIR=/tmp/bio-lab-uv-cache`。
- 测试尝试连接 Redis：确认命令前有 `CELERY_TASK_ALWAYS_EAGER=true`。
- OpenAI Key 错误：先运行不需要真实 LLM 的测试，或在 `.env` 设置有效 Key。

## 3. 阶段二：Docker Compose 三容器联调

确保 `.env` 中有真实 `OPENAI_API_KEY`，然后检查 Compose 展开结果：

```bash
docker compose config
```

预期：命令成功打印 `redis`、`api`、`worker` 三个服务，无 YAML 错误。

启动：

```bash
docker compose up --build
```

预期日志：

- Redis healthcheck 最终为 healthy。
- API 启动并监听 `0.0.0.0:8000`。
- Worker 显示 Celery worker ready，并连接 `redis`。

检查服务：

```bash
curl http://localhost:8000/health
docker compose ps
docker compose logs api worker redis
```

预期 API 输出：`{"status":"ok"}`；`docker compose ps` 中 Redis healthy、API/worker running。

Compose 当前配置检查结论：

- API 和 worker 使用相同 build context `.` 和同一 `Dockerfile`。
- API 与 worker 都挂载 `./output/jobs:/app/output/jobs`。
- Compose 默认网络同时连接三个服务，API/worker 使用服务名 `redis`。
- API 和 worker 都使用 `depends_on.redis.condition: service_healthy`，会等待 Redis healthcheck。
- healthcheck 使用 `redis-cli ping`，间隔 5 秒、超时 3 秒、重试 10 次，适合启动依赖。
- `OPENAI_API_KEY` 通过 Compose 插值传入 API 和 worker，但其他文献/独立模型变量目前不会自动传入，见问题清单。

如果失败：

- Redis unhealthy：`docker compose logs redis`，检查 Docker daemon 和 6379 端口。
- API/worker 一直 pending：确认 Redis healthy，并检查 `CELERY_BROKER_URL` 与 `CELERY_RESULT_BACKEND`。
- worker 找不到输出文件：确认宿主机 `output/jobs/` 与容器 `/app/output/jobs` 两边挂载一致。
- Key 缺失：运行 `docker compose config`，检查 `OPENAI_API_KEY` 是否为空；确认 `.env` 位于项目根目录。

## 4. 阶段三：Streamlit 前端连接

保持 Compose 的 API/worker/Redis 运行，在另一个终端执行：

```bash
export BACKEND_URL=http://localhost:8000
export MAX_UPLOAD_SIZE_GB=5
export POLL_TIMEOUT_MINUTES=30
uv run streamlit run app/app.py
```

Windows PowerShell：

```powershell
$env:BACKEND_URL="http://localhost:8000"
$env:MAX_UPLOAD_SIZE_GB="5"
$env:POLL_TIMEOUT_MINUTES="30"
uv run streamlit run app/app.py
```

打开 Streamlit 显示的地址。预期：

1. 可以选择自动判断、仅数据分析、仅文献检索、综合分析。
2. 文献任务隐藏上传框；数据和综合任务提示 `.h5ad` 必需。
3. 提交后显示阶段、百分比和耗时。
4. 完成后出现“分析结果”“文献综述”“原始输出”三个 Tab。

若 Streamlit 在容器内运行，`BACKEND_URL` 应使用 `http://api:8000`；若 Streamlit 在宿主机运行，应使用 `http://localhost:8000`。

## 5. 阶段四：真实 `.h5ad` 端到端

### 推荐数据：Scanpy PBMC 3k

直接用 Scanpy 下载公开 PBMC 3k：

```bash
uv run python - <<'PY'
import scanpy as sc

adata = sc.datasets.pbmc3k()
adata.write_h5ad("data/pbmc3k.h5ad")
print(adata)
PY
```

这会从 Scanpy 官方数据源下载约 3,000 个细胞的教学数据。也可参考 Scanpy 数据集页面：
<https://scanpy.readthedocs.io/en/stable/generated/scanpy.datasets.pbmc3k.html>

预处理提示：确认下载结果是 `.h5ad`，不要把 `data/` 下的原始数据提交到 Git；首次运行可能需要网络访问数据源。

在 Streamlit 中上传 `data/pbmc3k.h5ad`，选择“仅数据分析”，指令填写：

```text
完成基础单细胞 QC 并评估批次效应
```

预期：任务进入 Celery worker，输出 QC 前后统计、violin/scatter 图、批次效应评估和 provenance 文件。如果选择“综合分析”，还应在任务目录看到文献 JSON/Markdown 报告；文献摘要任务需要有效 OpenAI Key。

## 6. 五分钟自检脚本

在项目根目录执行以下脚本：

```bash
python - <<'PY'
import os
import socket
from pathlib import Path
from urllib.request import urlopen

checks = {
    "OPENAI_API_KEY": bool(os.getenv("OPENAI_API_KEY")),
    "BACKEND_URL": os.getenv("BACKEND_URL", "http://localhost:8000"),
    "BIO_LAB_JOB_DIR": os.getenv("BIO_LAB_JOB_DIR", "output/jobs"),
}
for key, value in checks.items():
    print(f"{key}: {'configured' if value is True else value}")

try:
    with socket.create_connection(("localhost", 6379), timeout=2):
        print("Redis: reachable")
except OSError as exc:
    print(f"Redis: unavailable ({exc})")

backend = os.getenv("BACKEND_URL", "http://localhost:8000").rstrip("/")
try:
    with urlopen(backend + "/health", timeout=3) as response:
        print("Backend:", response.status, response.read().decode())
except Exception as exc:
    print(f"Backend: unavailable ({exc})")

files = list(Path("data").glob("*.h5ad"))
print("h5ad files:", ", ".join(map(str, files)) if files else "none")
PY
```

预期至少看到：环境变量状态、Redis reachable（阶段二）、Backend `200`、以及一个 `.h5ad` 文件。阶段一没有 Redis/API 时，Redis 和 Backend 显示 unavailable 是正常的。

## 7. 常见错误速查表

| 错误信息 | 常见原因 | 修复 |
|---|---|---|
| `OPENAI_API_KEY is not configured` | API/worker 没有收到 Key | 在根目录 `.env` 设置并重启 Compose |
| `Connection refused localhost:6379` | Redis 未启动或 broker 地址错误 | 启动 Redis；Compose 内使用 `redis://redis:6379/...` |
| `Cannot connect to the Docker daemon` | Docker Desktop/daemon 未运行 | 启动 Docker，或先使用 eager 模式 |
| `Europe PMC API unavailable` | 外网、端点或速率限制 | 检查网络和 `EUROPE_PMC_URL`，稍后重试 |
| `未找到匹配文献` | 查询实体过宽或无结果 | 使用明确基因、细胞类型、疾病关键词 |
| `文件超过 5GB` | Streamlit 前端大小限制 | 降采样/拆分数据，或调整 `MAX_UPLOAD_SIZE_GB` 与后端限制一致 |
| `An .h5ad file is required` | 数据/综合任务未上传文件 | 上传 `.h5ad` 或选择仅文献检索 |
| 任务一直 `PENDING` | worker 未启动或 broker 不通 | 查看 `docker compose logs worker redis` |
| artifact `404` | 任务未完成、路径未共享或文件未生成 | 查看 `output/jobs/<task_id>/` 和 API/worker 日志 |
| Streamlit 查询超时 | 数据过大或 worker 忙 | 查看 worker 日志，调整 `POLL_TIMEOUT_MINUTES` |
| `ModuleNotFoundError` | 依赖未同步 | 执行 `uv sync --dev` |
