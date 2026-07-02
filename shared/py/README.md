# shared/py · 后端共享件（Python）

后端 `import` 用。各件最小可跑实现在 T6 落地：

- `glossary/` —— 术语表**只读查表**客户端（service_role）。`lookup` / `lookup_batch` / `load_map(source_lang,target_lang)->dict`。翻译与报价共用。
- `pdf_triage/` —— PyMuPDF 文本层分流。`triage_pdf(path)->[PageTriage]`：矢量 CAD 页(廉价文字提取) vs 扫描/手绘页(送视觉)；`render_page_png(...)`。
- `claude_client/` —— 服务端 Claude 封装（`claude-opus-4-8`，adaptive thinking）。`complete` / `complete_vision` / `stream_complete`，返回带 usage/cost。
- `supabase_client/` —— service_role 客户端初始化；约定读写私有数据必须显式带 `user_id`。
  （**故意不叫 `supabase`**，否则会遮蔽同名 pip 包 `supabase`。）
- `settings.py` —— 从 `.env` 读配置（`Settings.from_env()` / `load_env()`），无第三方依赖。
- `skills/` —— 从 5 个 skill 搬来的机械脚本（各模块 session 搬入；见 `skills/README.md`）。

**导入方式**：把 `shared/py` 加入 `PYTHONPATH`（Docker: `ENV PYTHONPATH=/app/shared/py`），
然后 `from glossary import GlossaryClient` / `from pdf_triage import triage_pdf` / `from claude_client import ClaudeClient` / `from supabase_client import service_client_from_env`。
依赖见 `requirements.txt`；冒烟测试 `tests/`（`pytest tests/`，5 项含真实 Supabase/Claude 集成）。
