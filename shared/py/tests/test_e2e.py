"""端到端：串起四基础件的后端管道 —— 造日文 PDF → 分流 → 术语批量查 → 未命中送 Claude 翻译。

需真实 Supabase + Claude；缺依赖/配置/网络则跳过。这是各模块（翻译/报价）将复用的
「查表命中就用词库、未命中回退 LLM」核心链路。
"""
import pytest


def _has_cjk(s: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in s)


def test_e2e_triage_glossary_then_llm_fallback(tmp_path):
    fitz = pytest.importorskip("fitz")
    pytest.importorskip("supabase")
    pytest.importorskip("anthropic")
    try:
        from settings import Settings

        s = Settings.from_env()
    except Exception as e:
        pytest.skip(f"缺少配置: {e}")

    from claude_client import ClaudeClient
    from glossary import GlossaryClient
    from pdf_triage import PageKind, triage_pdf
    from supabase_client import make_service_client

    # 1) 造一页日文 PDF，验证分流走「廉价文字提取」
    doc = fitz.open()
    pg = doc.new_page()
    # 需 >40 字符才走文字提取门（否则稀疏文本页按设计送视觉）
    pg.insert_text((72, 72), "壁面 天井 床 収納棚 化粧板 メラミン 天板 施工図 詳細 断面図")
    pg.insert_text((72, 110), "スケール 1:10 現場取付 コンセント 照明器具 点検口 巾木 見切り")
    path = str(tmp_path / "ja.pdf")
    doc.save(path)
    doc.close()
    pages = triage_pdf(path)
    assert pages[0].kind is PageKind.VECTOR_TEXT

    # 2) 术语批量查（真实 Supabase）
    g = GlossaryClient(make_service_client(s.supabase_url, s.supabase_service_role_key))
    terms = ["天井", "床", "壁面", "__绝不存在的词干__"]
    try:
        hits = g.lookup_batch(terms, "ja", "zh")
    except Exception as e:
        pytest.skip(f"Supabase 连接不可用: {e}")
    assert "__绝不存在的词干__" not in hits  # 未命中的确实不在结果里

    # 3) 「命中用词库、未命中回退 Claude」——对 天井 取一个中文译文
    target = "天井"
    if target in hits:
        translation = hits[target].target_term  # 词库命中
    else:
        c = ClaudeClient.from_env()
        try:
            r = c.complete(
                system="你是日中翻译。只输出中文译文，一个词，不要标点、不要解释。",
                user_text=f"把这个日语词翻成中文：{target}",
                max_tokens=32,
            )
        except Exception as e:
            pytest.skip(f"Anthropic API 不可用: {e}")
        assert r.usage.cost_usd() > 0
        translation = r.text.strip()

    assert translation and _has_cjk(translation), f"未得到中文译文: {translation!r}"
