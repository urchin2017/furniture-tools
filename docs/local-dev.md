# 本地一键启动（docker-compose）

在你自己的电脑上跑整套「家具出口内部工具」，浏览器点着用。数据仍连你 `.env` 里配置的
那套 Supabase（云端），**在本机浏览器可直连 Supabase，不需要任何转发器/代理**。

## 前置
- 装好 **Docker Desktop**（含 `docker compose`）。
- 你已有的 Supabase 项目（术语表/jobs 表、uploads/outputs 存储桶、登录账号都已就绪——
  你之前手动测试过，就是这套）。

## 步骤

```bash
# 1) 在仓库根，把示例配置复制成 .env 并填真值
cp .env.example .env
#   需要填：
#   NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY
#   SUPABASE_SERVICE_ROLE_KEY / ANTHROPIC_API_KEY
#   （NEXT_PUBLIC_API_BASE_URL / API_BASE_URL / API_CORS_ORIGINS 用默认值即可）

# 2) 构建并启动（首次约几分钟：后端要装 LibreOffice，前端要装 npm 依赖）
docker compose up --build

# 3) 打开浏览器
#    前端 http://localhost:3000  （用你的 Supabase 账号登录）
#    后端 http://localhost:8000/health  → {"status":"ok"}
```

停止：`Ctrl-C`，或另开终端 `docker compose down`。

## 用法
登录 → 左侧「报价」→ 选图纸 PDF + 报价模板 Excel + 填项目名 → 「开始生成」。
生成完成后可看 AI 成本明细、尺寸摘要（待确认维会标淡黄）、渲染验证图，并下载 xlsx。

## 说明 / 排错
- **改了 `.env`**：重启容器生效（`docker compose up`）。前端用 dev 模式，`NEXT_PUBLIC_*`
  运行时读取，无需重建镜像。
- **模型**：服务端用 `.env` 里的 `CLAUDE_MODEL`（当前 `claude-sonnet-5`）。
- **成本**：每次生成会真实调用 Anthropic 视觉模型，按 token 计费（一张 2 页图约 US$0.1）。
- **端口占用**：3000/8000 被占时，改 `docker-compose.yml` 里的 `ports` 左值（如 `3001:3000`），
  并把 `.env` 的 `NEXT_PUBLIC_API_BASE_URL`/`API_CORS_ORIGINS` 同步改成对应端口。
- **只想跑测试**：后端 `docker compose run --rm api pytest`（或本机 `pytest shared/py/tests`、
  `pytest apps/api/tests` 分开跑——两目录有同名测试文件，别一起跑）。
- **`.env` 绝不入库**，也不会进镜像层（`.dockerignore` 已排除）。
