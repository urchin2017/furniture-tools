# shared 共享件

- **`ts/`** 给前端 import：`glossary`（术语表 CRUD 客户端）、`supabase`（浏览器客户端）、`types`（DTO 类型）。
- **`py/`** 给后端 import：`glossary`（只读查表）、`pdf_triage`（PyMuPDF 文本层分流）、`claude_client`（服务端 Claude 封装）、`supabase`（service_role 客户端）、`skills`（从各 skill 搬来的机械脚本）。

原则：同一逻辑 `ts`/`py` 两份实现，都指向**同一张 Supabase 表**，靠 schema 对齐；不做跨语言复用。

（各件的最小可跑实现在 T6 落地；`skills/` 的脚本在各模块 session 搬入。）
