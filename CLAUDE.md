# 家具出口内部工具 · 顶层 CLAUDE.md

> 本仓库把「已做好的 Claude Skill」组装成一个 Web 工具，给没有 API key 的销售同事用，所有 AI 调用走服务端 key。
> 完整规划见 plan：`~/.claude/plans/claude-code-ticklish-thunder.md`

## 架构
- **前端 `apps/web`**：Next.js(React, App Router)。简单读写（登录、术语表 CRUD）直连 Supabase（anon key + RLS）。
- **后端 `apps/api`**：FastAPI(Python)。重任务（报价/图纸/唛头处理、调 Claude API、跑 skill 机械脚本）走这里。
- **数据 Supabase**：Postgres + Auth + Storage，用 RLS 做数据隔离。
- **`shared/`**：`ts` 给前端、`py` 给后端；同一逻辑两份实现，都指向同一张 Supabase 表。

## 功能模块（三大块，功能实现留给各自 session）
- **模块 A｜报价**：报价单生成（skill `drawing-to-quotation-2026-07-02-v5`，原 `-2026-07-01-v3` 已下架）、报价单对比（`excel-quote-compare-2026-03-24`）
- **模块 B｜图纸**：图纸翻译（`drawing-translator-2026-04-21`）、改版差异（单品 `drawing-revision-diff-remark-2026-06-01` / 整套 `zhengtao-tuzhi-gaiban-chayi-2026-06-02`）
- **模块 C｜唛头**：唛头生成（`product-list-to-shipping-marks-2026-04-23`，先占位）

## 关键原则
- **Skill 拆两半**：机械脚本（PyMuPDF/openpyxl/裁图/渲染/weasyprint/reportlab）原样复用，放 `shared/py/skills` 或各 module；判断步骤（定尺寸/匹配/翻译/找差异）改后端调 Claude API，SKILL.md 的 prose 当 system prompt。
- **术语表单一真相源**：Supabase `glossary` 表。报价的日→中翻译 与 图纸翻译 **共用同一张表**；前端可视化 CRUD。
- **成本控制**：PyMuPDF 文本层分流——矢量 CAD 页走廉价文字提取，扫描/手绘页才送视觉模型。
- **数据隔离**：共享资源（`glossary`/`factory_profiles`，登录可读）+ 私有任务（`jobs`/上传文件按 `user_id`，admin 看全部）。前端走 anon+RLS；后端走 service_role 但**必须显式带 `user_id`**。
- **单工厂优先**：报价先做创明/Chuangming，profile 存 Supabase，加工厂=加 profile 不改代码。
- **模型**：服务端 Claude 封装用 `claude-opus-4-8`，adaptive thinking（`thinking={"type":"adaptive"}`，不要 `budget_tokens`）。

## Monorepo 约定
- 单一仓库装下整个项目（前端/后端/数据库脚本/共享代码），备份 = 克隆这一个仓库。
- **不同 session 只写自己的子文件夹，不做最后拼接**：模块 X 的 session 只动 `apps/api/app/modules/X`、`apps/web/app/(app)/X`、必要时 `shared/`。
- 每个模块子文件夹自带 `CLAUDE.md` 说明本模块约定。

## GitHub 备份
- 私有仓库当云端备份。上传由用户一句话触发（"帮我上传/备份"），助手替其跑 `git add -A && git commit && git push`；不配自动 hook、不定时。
- `.env` 绝不入库（见 `.gitignore`）。

## 环境
- Node ≥ 20（本机 v22）、**npm workspaces**（未用 pnpm）。
- Python 后端在 Docker 里跑（镜像 3.11）；本机 `python3` 为 3.9，仅供轻量脚本。
- 密钥放 `.env`（见 `.env.example`）。
