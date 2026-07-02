# 交接笔记 · 家具出口内部工具（截至 2026-07-02，阶段 0 全部完成后）

> 新 session 从这里接手。完整规划见 `~/.claude/plans/claude-code-ticklish-thunder.md`，
> 全局约定见顶层 `CLAUDE.md`，项目状态记忆会自动加载（`furniture-tools-project.md`）。

## 一、关键坐标

- **仓库根**：`/Users/urchin/Dropbox/Cowork/Projects/Furniture System_2026-06-29/furniture-tools/`（在 Dropbox 里，见坑 #4）
- **GitHub**（云端备份，私有）：`github.com/urchin2017/furniture-tools`，`gh` 已登录为 `urchin2017`。git 已同步到 `main`。
- **Supabase 项目 ref**：`kyzbquqjekrzxzudekgu`。SQL Editor：`https://supabase.com/dashboard/project/kyzbquqjekrzxzudekgu/sql/new`
- **密钥**：都在 `furniture-tools/.env`（**gitignore，不入库**）—— Supabase URL/anon(publishable)/service_role(secret)、`ANTHROPIC_API_KEY`。新 key 格式 `sb_publishable_`/`sb_secret_`。
- **管理员账号**：`xianyingjie@gmail.com`（登录密码在你自己的笔记里；忘了可用 Supabase Auth 重置）。
- **模型**：`claude-opus-4-8` + adaptive thinking（`thinking={"type":"adaptive"}`，**不要** `budget_tokens`）。已验证可用，定价 $5/$25 每 1M。
- **上传规则**：**你说「帮我上传」**我才 `git add -A && git commit && git push`；不自动、不定时。

## 二、已完成（阶段 0：10/10，全部完成）

- **T1** monorepo 骨架 + 私有仓库 + 首次 push。
- **T2** `.env` / `.env.example`（密钥齐全，不入库）。
- **T3** Supabase schema + RLS（`supabase/migrations/0001_init.sql`，经 SQL Editor 跑）：`profiles`(角色)、`glossary`、`factory_profiles`、`jobs`、storage 桶 `uploads`/`outputs`。共享资源 + 私有任务两种 RLS，`is_admin()` 判角色。
- **T4** 登录鉴权：前端 `/login`（邮箱+密码）+ `middleware.ts` 未登录重定向。**注意**：只做了前端↔Supabase，**FastAPI 后端未建**（见坑 #5）。
- **T5** 占位外壳 + 主题 token 接缝（导航：报价/图纸/唛头/术语表）。
- **T7** 术语表 seed 677 条（日→中 431、英→中 246）。
- **T8** 术语表 CRUD 页（全栈垂直闭环），已在真实 Chrome 端到端验证。
- **apps/api 建成**：`app/main.py`(CORS+挂路由)、`config.py`(把 `shared/py` 塞进 `sys.path`)、`auth.py`+`deps.py`(鉴权不存 JWT secret，直接用 service_role 客户端调 `supabase.auth.get_user(token)` 问 Supabase Auth，无效/过期抛 401)、`routers/{health,glossary,jobs}.py`（`glossary` 是只读批量查表端点给后续模块用；`jobs` 是建/查骨架，真正异步执行留给 T10）。本机 python3.9 直跑需要额外装 `eval-type-backport`（FastAPI/pydantic 在 3.9 上没法对 `from __future__ import annotations` 产生的 `X | None` 求值，3.11 的 Docker 镜像不需要，已写进 `apps/api/requirements.txt` 并加注释）。
- **T9 本地 Docker 完成**：`docker/Dockerfile.api`(python:3.11-slim + LibreOffice/poppler/ImageMagick/CJK字体)、`docker/Dockerfile.web`(node:20-slim 两段式 `npm ci`+`next build`/`next start`，**没用** `output:'standalone'`——npm workspaces 下 standalone 的 tracing 很容易出幺蛾子，选了更笨重但可靠的完整 `node_modules` 方案）、`docker-compose.yml`、根 `.dockerignore`。**已用 `docker compose up --build` 实跑验证**：两个容器都起来了，浏览器登录态延续、术语表增删查全通过（1243→1244→1243），容器内 `soffice --version`/`pdftotext -v`/`python -c "import fitz"`/`convert -version` 全过。验证完已 `docker compose down`，3000 端口让回日常 `next dev`。
- **验证 T9 过程中顺手修的 bug**：`apps/web/lib/supabase/{middleware,server}.ts` 的 `setAll(cookiesToSet)` 参数没类型标注——`next dev` 不做严格类型检查所以之前没暴露，`next build`（Docker 必经）会报 `TS7006` 直接挡住构建。已加 `CookieOptions` 类型标注修复，跑过 `tsc --noEmit` + 浏览器验证登录/跳转正常。
- **T10 jobs 异步骨架完成**：`apps/api/app/tasks/runner.py`——`run_job(supabase, job_id, feature, params)` 由 `routers/jobs.py` 的 `POST /api/jobs` 用 FastAPI `BackgroundTasks` 触发，跑完把 `status/progress/output_files/error` 写回 `jobs` 表；`JobContext.report_progress(pct)` 给 handler 用来汇报中途进度；前端轮询 `GET /api/jobs/{id}` 拿状态。**业务逻辑按 feature 注册进 `runner.HANDLERS: dict[str, JobHandler]`**（现在是空的——三大模块的 session 实现完 handler 后自己注册进去，例如 `HANDLERS["quote_generate"] = quote_generate_run`）；没注册的 feature 会直接把 job 标 `status='error'`（error 里写"功能模块 xxx 尚未实现"），**不会**静默卡在 `queued`。`apps/api/tests/` 已补齐六维度测试（**24 项全绿，23 项纯离线 + 1 项网络门控**）：
  - **单元**（`conftest.py` 假 Supabase 桩，无网络）：`test_auth.py`(verify_token/fetch_role)、`test_deps.py`(get_current_user 鉴权头解析/require_admin)、`test_runner.py`(run_job 三条路径)。
  - **边界/异常**：`test_deps.py` 里缺 header/错 scheme/空 token 等参数化用例；`test_regression.py` 里查不到的 job_id 返回 404 而非报错。
  - **集成 + 端到端**：`test_e2e.py` 不 override 任何依赖，走真实 Supabase Auth 网络请求校验"无效 token 必 401"（缺 .env/网络会自动 skip，不阻塞离线跑）。
  - **回归**：`test_regression.py`——① OpenAPI schema 能正常生成（锁死 eval-type-backport 相关坑）；② 未注册 feature 的任务不会静默卡在 `queued`；③ **service_role 绕过 RLS 时 jobs 的用户隔离不能失效**（sales 之间互相看不到任务，只有 admin/本人能看，查他人任务返回 404 不是 403，不暴露任务是否存在）。
  - **黄金文件**：`test_golden.py` 把 API 路由表快照进 `golden/routes.json`，路由被意外增删改会被抓到（`UPDATE_GOLDEN=1 pytest tests/test_golden.py` 重新生成）。
  - 另外已在 Docker（python 3.11）里重新构建 api 容器验证过启动正常。
- **术语表额外功能**（超出原计划，都已做并验证）：
  - **导入 Excel/CSV**（`apps/web/lib/glossaryImport.ts` + `xlsx`；按「源+目标+原文+领域」唯一键 upsert 替换/新增；带下载模板）。
  - **任意语向**添加/筛选（源+目标语言，筛选按数据实际语向动态列出）；删除改成**页面内联确认**（弃用原生 `confirm()`）。
  - **反转脚本** `scripts/reverse_glossary.cjs`：把 →中 词条批量反转成 中→日/中→英 草稿，经子代理校对后导入 **566 条**（zh→ja 349 / zh→en 217）。
  - **前端分页取全**修复（PostgREST 1000 行上限，见坑 #2）。
- **T6** `shared/py` 后端四基础件 + 6 类测试（**32 项全绿**）：
  - `glossary/`（lookup/lookup_batch/load_map，**分页取全**）、`pdf_triage/`（triage_pdf/render_page_png 文本层分流）、`claude_client/`（complete/complete_vision/stream_complete，opus-4-8 adaptive thinking，`Usage.cost_usd()`）、`supabase_client/`（service_role，**改名避坑** 见 #3）、`settings.py`。
  - 测试类型：单元(假桩) / 集成(真实 Supabase·Claude) / 回归 / 边界·异常 / 端到端 / 黄金文件。25 项纯离线 + 7 项网络门控。

**术语表 DB 现状**：**1243 条** —— 日→中 431、英→中 246、中→日 349、中→英 217。`domain=''` 常规，`domain='test'` 为测试数据（现无）。校对时排除的 89 条（存疑12+非术语77）**未入库**，留在 `Furniture System_2026-06-29/术语表反转_待确认/存疑与非术语_待处理.xlsx`（仓库外，未提交）。

**报价生成 skill 版本更正**：`drawing-to-quotation-2026-07-01-v3` **已下架**，现在唯一有效版本是 **`drawing-to-quotation-2026-07-02-v5`**（`~/Dropbox/Cowork/Skill/quote skill/` 下唯一的 .skill 文件）。`CLAUDE.md`、`apps/api/app/modules/README.md`、`shared/py/skills/README.md`、`~/.claude/plans/claude-code-ticklish-thunder.md`（仓库外）都已同步改成 v5，且 `shared/py/skills/README.md` 的脚本清单是**解压 v5 包实际核实过的**（非推测）：四步管线 `extract_scaffold.py`(含光栅页⚠RASTER判定)→ 定外形尺寸(几何或看图协议，看图配合新脚本 `render_pages.py`)→ `fill_quote.py`(无照片时配合新脚本 `crop_drawings.py`)→ `render_check.py`。**v5 相比 v3 新增两个脚本**：`render_pages.py`、`crop_drawings.py`。`supabase/README.md` 里那句提历史数据来源的话没改（陈述既成事实，不是版本指针）。

## 三、下一步（阶段 0 已全部完成，开始三大模块）

阶段 0（T1~T10）全部做完了。接下来是三大模块（A 报价 / B 图纸 / C 唛头），把各 skill 的机械脚本搬进 `shared/py/skills/`、判断步骤改调 `claude_client`（搬运指引见 `shared/py/skills/README.md` 和 plan 的「路线图」）。每个模块大致要做：

1. **机械脚本原样搬进** `shared/py/skills/<对应skill>/` 或 `apps/api/app/modules/<m>/`；**判断步骤**（定尺寸/匹配/翻译/找差异）改调 `shared/py/claude_client`，原 SKILL.md 的 prose 当 system prompt。
2. **实现 `runner.JobHandler`**（`JobContext -> dict`），注册进 `apps/api/app/tasks/runner.HANDLERS[<feature>]`（见二.T10）。
3. **前端页面**：`apps/web/app/(app)/<module>/` 建 `page.tsx`，调 `POST /api/jobs` 建任务、轮询 `GET /api/jobs/{id}` 拿进度/结果。
4. **⚠️ Python 依赖缺口**：`shared/py/requirements.txt` 目前只有 `anthropic/supabase/pymupdf/pillow/numpy`，**没有 `weasyprint`/`openpyxl`/`reportlab`/`pypdf`**——用到时自己按需加进去；Dockerfile.api 的系统库（libpango/cairo/CJK字体/LibreOffice/poppler/ImageMagick）已经装好，只差 Python 包，加完包不用改 Dockerfile。

**模块实现顺序：按 A 报价 → B 图纸 → C 唛头做**（用户明确要求，不按复杂度从简到难排）。三个模块的相对复杂度供心里有数（不代表实现顺序）：**A 报价最重**——"定外形尺寸"是纯视觉判断步骤，且这个 skill 自己 v2→v3→v5 反复重写就是因为真实图纸尺寸算错，**第一个模块就啃最难的这块，要预留跟真实图纸对账迭代的余量，别指望一次到位**；B 图纸中等（翻译判断步骤能直接复用 T6 的 glossary/claude_client）；C 唛头最简单（三个脚本全是纯机械脚本，没有 Claude 判断步骤，放最后做）。

## 四、未解决的坑 / 注意事项

1. **本机网络/TLS 抖动**：curl 要 `--retry`；`git push` 靠 `gh` 凭据助手 + 重试循环。Python 网络本 session 通（pip/httpx 都成），但历史上出过 SSLEOFError——保留重试习惯。
2. **PostgREST 单次最多 1000 行**：`.limit(大数)` 会被服务端盖住，超过 1000 静默漏数据。前端 `glossary` load() 已改 range 分页；`shared/py` glossary.load_map 已分页。**将来任何全表读都要分页**。
3. **`supabase` 包名遮蔽**：后端本地包叫 **`supabase_client`**，绝不能改回 `supabase`（否则 `from supabase import create_client` 指向自己→崩）。
4. **仓库在 Dropbox 里**：Dropbox 同步 `.git`/`node_modules` 可能和 git/构建打架。建议把这两个设成「不同步」或把仓库挪出 Dropbox（**尚未处理**）。
5. ~~FastAPI 后端还没建~~ **已建成**（见二.apps/api），本坑作废。
6. **本机 Python 3.9**（Docker 里是 3.11）。`shared/py` 已加 `from __future__ import annotations` 兼容 3.9；`apps/api` 同样加了这个但 FastAPI/pydantic 在 3.9 上没法对 `X | None` 求值，本机直跑需要额外 `pip install eval-type-backport`（已写进 `apps/api/requirements.txt`，Docker 里的 3.11 用不上但装了也无害）。测试 venv 在 `scratchpad/venv_shared`、`scratchpad/venv_api`（临时目录，可能被清）——新 session 重建：`python3 -m venv` 后 `pip install -r shared/py/requirements.txt [-r apps/api/requirements.txt]`。
7. **DB 变更方式**：建表(DDL)在 Supabase 网页 **SQL Editor 粘贴运行**（没用 PAT/CLI）；数据增删（seed/导入/清理）用 secret key 走 REST。
8. **术语表新格式 key**：`sb_publishable_`=anon（前端）、`sb_secret_`=service_role（后端），当前 SDK 版本可用。
9. **本机没装 Homebrew/Docker Desktop**（2026-07-02 当场装的）：装 Homebrew 那步需要交互输入密码，agent 跑不了非交互安装；Docker Desktop 首次启动也要手动过一次权限弹窗。都装好后 `docker info` 能看到 `ServerVersion` 就说明可用，**Docker Desktop 窗口不弹出来不代表没在跑**——后台进程在 `ps aux | grep docker` 里能看到，`docker info` 能连上就行，不用纠结窗口。
10. **`docker compose -f docker/docker-compose.yml up` 必须带 `--env-file .env`**：`-f` 指定子目录下的 compose 文件时，Compose **不会**自动去仓库根找 `.env` 做 `${VAR}` 插值，不带这个参数 `NEXT_PUBLIC_*` 会被悄悄置空（`env_file: ../.env` 这种运行时注入不受影响，只有 build-arg 插值受影响）——实测踩过，`docker/README.md` 已更新成正确命令。
11. **`next build` 比 `next dev` 严格**：`apps/web/lib/supabase/{middleware,server}.ts` 的 `setAll(cookiesToSet)` 缺类型标注在 `next dev` 下不报错，Docker 里 `next build` 会因为 `strict: true` 报 `TS7006` 直接挡住构建。已修（加 `CookieOptions` 类型），但提醒：以后改前端代码后想确认 Docker 能不能过，本机跑一下 `npx tsc --noEmit -p apps/web/tsconfig.json` 比等 Docker 慢慢构建再报错快得多。

## 五、怎么重启环境（新 session 开场）

- **跑前端**：`preview_start` name=`web`（launch.json 在父目录 `.claude/launch.json`，端口 3000）。登录后可用术语表。真实浏览器测试用 claude-in-chrome（`list_connected_browsers` 确认扩展在）。
- **跑后端测试**：见坑 #6 建 venv，然后 `cd shared/py && <venv>/bin/pytest tests/ -q`（离线 25 项过；网络 7 项需 .env）；`apps/api` 的测试是 `cd apps/api && <venv>/bin/pytest tests/ -q`（24 项，六维度全覆盖，23 项纯离线 + 1 项网络门控需 .env）。
- **跑整套 Docker（T9 验收过的流程）**：仓库根目录跑 `docker compose -f docker/docker-compose.yml --env-file .env up --build`（**别漏 `--env-file .env`**，见坑 #10）。跑之前如果 `preview_start` 的 web 还占着 3000 端口，先 `preview_stop` 或 `docker compose ... down` 冲突的那个。日常开发用 `preview_start`（有 HMR，更快），Docker 只在要验证"整套能不能从零跑起来"时用。
- **git 状态**：`git -C <repo> log --oneline -1` 应见 `docs: 报价生成 skill 引用从 v3 更新为 v5…`（`9dda1db` 或更新）。
