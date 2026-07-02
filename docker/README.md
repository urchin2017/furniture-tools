# docker

- **`Dockerfile.api`** —— 后端镜像（`python:3.11-slim`）。装 LibreOffice / poppler-utils / weasyprint(+libpango/cairo) / 中日 CJK 字体 / ImageMagick，`pip install` 叠加 `shared/py/requirements.txt` + `apps/api/requirements.txt`，`ENV PYTHONPATH=/app/shared/py`。
- **`Dockerfile.web`** —— 前端镜像（`node:20-slim`，两段式：build 用 root `npm ci` + `next build`，运行段 `npm ci --omit=dev` + `next start`）。`NEXT_PUBLIC_*` 是**构建期** build-arg（内联进浏览器 bundle），不是运行时 env。
- **`docker-compose.yml`** —— 本地一键起 web+api（连云端 Supabase，不本地起 Postgres）。**在仓库根目录**跑：
  ```
  docker compose -f docker/docker-compose.yml --env-file .env up --build
  ```
  **⚠️ 必须带 `--env-file .env`**：`-f` 指定子目录下的 compose 文件时，Compose 不会自动去仓库根找 `.env` 做变量替换（`docker compose ... config` 可验证——不带这个参数 `NEXT_PUBLIC_*` 会被悄悄置空，实测踩过）。`env_file: ../.env`（容器运行时注入）不受此影响，只有 `${VAR}` 这种 build-arg 插值受影响。
- 构建 context 一律是**仓库根**（两个 Dockerfile 都要同时拿到 `shared/`），根 `.dockerignore` 排除了 `node_modules/.next/venv/.env` 等。

验收：`docker compose up` 后浏览器打开 `localhost:3000` 能登录、术语表 CRUD 通；容器内 `soffice --version` / `pdftotext -v` / `python -c "import fitz,weasyprint,openpyxl"` 全过（**⚠️ `weasyprint`/`openpyxl` 当前不在 `shared/py/requirements.txt` 里，跑各模块前需要先补上**，见 [[furniture-tools-project]]）。

（**需先装 Docker Desktop**，本机尚未装——见仓库 HANDOFF.md「未解决的坑」。）
