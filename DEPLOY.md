# 上云部署跑手册（Render + 云端 Supabase）

> 目标：把前端 + 后端从本地 Mac 搬到 Render（新加坡区，网络通畅），
> 摆脱本地 VPN/网络对 Claude API 调用的干扰。Supabase 保持不动（已在云上）。
> 决策理由与成本见对话记录 / HANDOFF.md。

## 为什么这样部署

- **本地网络是唯一痛点**：代码已证明能跑通（真实 15 页图纸 $1.74、与手工版 15/16 一致）。
  失败全是本地→Anthropic 这段网络时好时坏（超时 / 403 Request not allowed）。
- **搬到 Render 后**：Claude 调用变成 Render(新加坡) → Anthropic，稳定；用户浏览器只干轻活
  （登录、上传到 Render、轮询进度），那段脆弱的重活离开了本地。

## 架构（部署后）

```
用户浏览器 ──HTTPS──> Render:web (Next.js)     ← 静态页面/交互
          ──HTTPS──> Render:api (FastAPI)     ← 上传、建任务、看图定尺寸(调 Claude)、填表
Render:api ────────> Supabase (DB/Auth/Storage)  ← 云到云，稳
Render:api ────────> Anthropic API (Claude)      ← 云到云(新加坡)，稳，不再靠本地网络
```

## 一次性准备（谁做：括注）

### 0. 账号（你）
- 注册 Render 账号（render.com），绑定付款方式。**账单在你名下**——这一步只能你本人做。
- 代码要能被 Render 拉取：把仓库推到 GitHub（已有私有仓库 `github.com/urchin2017/furniture-tools`），
  在 Render 里授权访问该仓库。

### 1. 建 api 服务（我 + 你点授权）
- New → Web Service → 选仓库 → Runtime 选 **Docker**。
- Dockerfile 路径：`docker/Dockerfile.api`；Docker build context：仓库根 `.`。
- Region：**Singapore**。
- 实例规格：**至少 2GB 内存**（LibreOffice 渲染验证图内存吃得凶）。
  - 省钱选项：若不要"渲染验证 PNG"这个功能（成品 xlsx 不受影响，代码已做优雅降级），
    可用更小实例；届时可从镜像里去掉 libreoffice。
- Health Check Path：`/health`。
- **实例不能休眠**（任务要跑约 20 分钟，休眠会把后台任务杀掉）→ 用付费常驻实例，别用会 spin-down 的免费档。
- 环境变量（Environment）填：
  - `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`ANTHROPIC_API_KEY`（从本地 `.env` 复制，**绝不进 Git**）
  - `API_CORS_ORIGINS` = web 服务的最终网址（见第 3 步回填，如 `https://furniture-web.onrender.com`）

### 2. 建 web 服务（我 + 你点授权）
- New → Web Service → 同一仓库 → Runtime 选 **Docker**。
- Dockerfile 路径：`docker/Dockerfile.web`；context：仓库根 `.`。
- Region：Singapore。小实例即可（前端很轻）。
- **⚠ NEXT_PUBLIC_* 是"构建期"变量**（会被 next build 内联进浏览器包），必须作为
  **Docker build args** 传进去，光设运行时环境变量对客户端代码不生效：
  - `NEXT_PUBLIC_SUPABASE_URL`
  - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
  - `NEXT_PUBLIC_API_BASE_URL` = api 服务的最终网址（如 `https://furniture-api.onrender.com`）
  - 在 Render 里通过 "Docker Build Arguments" 设置这三个（不是普通 env）。

### 3. 回填跨域 + Supabase 允许网址（我）
- 两个服务各自拿到 `*.onrender.com` 网址后：
  - 把 web 的网址填进 api 的 `API_CORS_ORIGINS`，重启 api。
  - Supabase 后台 → Authentication → URL Configuration：把 web 网址加进
    Site URL / Redirect URLs（否则登录跳转会被拒）。

### 4. 端到端验收（我 + 你）
- 打开 web 网址 → 登录 → 用真实压缩版图纸 + 模板跑一次 → 确认稳定出成品。
- 关掉本地 VPN 也应当照样能用（因为重活已在 Render 侧）。

### 5. 发给同事（你）
- 直接发 web 网址。同事用各自 Supabase 账号登录（在 Supabase 后台建账号即可）。

## 成本

| 项 | 金额 | 说明 |
|---|---|---|
| Render api（2GB 常驻） | ~$25/月 | 主要成本；不要 LibreOffice 可降到更小实例更便宜 |
| Render web（小实例） | ~$7/月 | 前端很轻 |
| Supabase | $0（免费额度） | 数据/存储涨太多才升 Pro（$25/月） |
| Claude API | ~$1.7/份报价 | 按页数，用多少付多少 |
| 域名（可选） | ~$10–15/年 | 不要可用 `*.onrender.com` |

合计约 **$32/月固定 + 每份报价 $1.7**（去掉渲染验证可再省 api 实例钱）。

## 已知坑（都已在代码/配置里处理或在此标注）

1. **NEXT_PUBLIC_* 必须走 build args**（见第 2 步），否则前端连不上后端。
2. **api 实例要 ≥2GB 且不休眠**：LibreOffice 内存 + 20 分钟长任务。
3. **上传大文件走后端中转 `/api/uploads`**（已实现），不是浏览器直传，避免大文件断。
4. **鉴权带缓存 + 重试**（已实现 `app/auth.py`），Supabase 抖动不至于每请求都挂。
5. **长任务是 FastAPI 后台任务，跑在 web 进程里**：实例重启/重新部署会中断在跑的任务
   （和本地一样）。要更稳需引入真正的任务队列，属后续增强，非上线阻塞项。
6. **密钥只放 Render 环境变量**，永不进 Git（`.env` 已 gitignore）。

## 需要你先做的唯一一步

**注册 Render 账号（render.com，注册免费，只有开付费实例才计费），
并把仓库最新代码推到 GitHub（跟我说"帮我上传"我来推）。**
账号好了告诉我，我们一起点完上面 1–4 步，当天上线。
