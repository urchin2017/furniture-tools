# apps/web · 前端（Next.js, App Router）

- 登录后在 `app/(app)/` 下按模块分页：`quote/{generate,compare}`、`drawings/{translate,revision-diff}`、`shipping-marks`、`glossary`。
- **简单读写**（登录、术语表 CRUD）直连 Supabase（`shared/ts/supabase`，anon key + RLS）。
- **重任务**调后端 `apps/api`，请求带 `Authorization: Bearer <supabase access token>`。
- **外壳/主题**：`components/theme` 是 Claude Design 换入的接缝，design token 集中在这里，方便整套替换。占位外壳先用中性样式。
- **加新模块页**：在 `app/(app)/<module>/` 建 `page.tsx`，并在导航（`components/layout`）加一项。只动自己模块的目录。
