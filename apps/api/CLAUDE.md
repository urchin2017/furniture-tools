# apps/api · 后端（FastAPI）

- `app/main.py` 挂路由；`routers/` 放端点；`modules/` 每个功能一个子包（`quote/{generate,compare}`、`drawings/{translate,revision_diff}`、`shipping_marks`）。
- **判断步骤**调 `shared/py/claude_client`（`claude-opus-4-8`）；**机械脚本**从对应 skill 搬进 `shared/py/skills` 或本模块，尽量原样复用。
- **鉴权**：`deps.py` 注入 `current_user`（校验 Supabase JWT → user_id/role）；后端用 service_role 客户端，但**必须显式带 `user_id`** 做隔离。
- **长任务**：用 `tasks/runner.py` 的异步任务 + 写 `jobs.progress`，前端轮询（替代 skill 里 45s bash 超时的进度保存 hack）。
- **加新模块**：在 `modules/<m>/` 写逻辑，`routers/` 加对应端点，别动别的模块子文件夹。
