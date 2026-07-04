"""模块 A · quote_generate 测试（纯离线：假 Supabase storage + 假视觉判断）。

覆盖：单元（extract_json/_clean_product/merge/术语命中/重复品番/路径安全）、
集成（handler 全管线编排：下载→骨架→假视觉→填表→上传）、回归（HANDLERS 注册）。
"""
from __future__ import annotations

import json

import fitz
import pytest
from openpyxl import Workbook

from app.modules.quote import dims, generate
from app.modules.quote.dims import PageDecision
from app.tasks.runner import HANDLERS, JobContext


# ---------- 单元：dims 辅助 ----------

def test_extract_json_variants():
    assert dims.extract_json('{"products": []}') == {"products": []}
    assert dims.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert dims.extract_json('前置解释 {"a": {"b": 2}} 后置') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        dims.extract_json("没有任何 JSON")


def test_clean_product_coerces_and_guards():
    p = dims._clean_product(
        {"row_code": " f01a ", "W": "1,200", "D": 850.4, "H": None, "qty": "3",
         "dim_source": "随便写的", "mat_jp": ["A", ""], "mat_cn": None}
    )
    assert p["row_code"] == "F01A"
    assert p["W"] == 1200 and p["D"] == 850 and p["H"] is None and p["qty"] == 3
    assert p["dim_source"] == "PENDING", "非法 dim_source 必须落回 PENDING（铁律五）"
    assert p["mat_jp"] == ["A"] and p["mat_cn"] == []


def test_clean_product_sanitizes_confirm_dims():
    # 合法维度保留、非法维度剔除、顺序按输入
    assert dims._clean_product({"row_code": "F01", "confirm_dims": ["W", "X", "H"]})["confirm_dims"] == ["W", "H"]
    # 缺省 → []（透传给 fill_quote 不标黄）
    assert dims._clean_product({"row_code": "F01"})["confirm_dims"] == []
    # None → []
    assert dims._clean_product({"row_code": "F01", "confirm_dims": None})["confirm_dims"] == []
    # 三维齐全
    assert dims._clean_product({"row_code": "F01", "confirm_dims": ["W", "D", "H"]})["confirm_dims"] == ["W", "D", "H"]


def test_system_prompt_instructs_confirm_dims():
    from app.modules.quote.prompts import SYSTEM_PROMPT
    # 任务3(B)：system prompt 必须要求模型逐维产出 confirm_dims，且在输出示例里带该键
    assert "confirm_dims" in SYSTEM_PROMPT
    assert "逐维待确认" in SYSTEM_PROMPT, "需有判定规则段，模型才知道何时标某维"
    assert '"confirm_dims":["W"]' in SYSTEM_PROMPT, "输出格式示例应带 confirm_dims 键"


def test_merge_preserves_confirm_dims():
    scaffold = [_rec("F01")]
    decision = PageDecision(products=[_vis("F01", confirm_dims=["W", "H"])], cost_usd=0.0)
    merged = dims.merge_page_decision(scaffold, decision)
    assert merged[0]["confirm_dims"] == ["W", "H"], "视觉给出的逐维待确认应随 rec.update 透传到合并结果"


def _rec(code, page=2, **kw):
    base = {
        "row_code": code, "page": page, "page_image": f"pages/full_page_{page:02d}.png",
        "name_jp": "", "name_cn": "", "mat_jp": [], "mat_cn": [],
        "W": None, "D": None, "H": None, "qty": None, "qty_hint": None,
        "dim_source": "PENDING", "dim_evidence": "",
        "measured": {"vector_ok": False}, "text_dims": {"W": None, "D": None, "H": None},
        "note_jp": "", "note_cn": "",
    }
    base.update(kw)
    return base


def _vis(code, **kw):
    p = {"row_code": code, "name_jp": "テーブル", "name_cn": "桌", "mat_jp": [], "mat_cn": [],
         "W": 1200, "D": 850, "H": 725, "qty": 1, "dim_source": "visual",
         "dim_evidence": "外形寸法線", "note_jp": "", "note_cn": ""}
    p.update(kw)
    return dims._clean_product(p)


def test_merge_updates_adds_variant_and_keeps_missed_pending():
    scaffold = [_rec("F01"), _rec("F02")]
    decision = PageDecision(products=[_vis("F01"), _vis("F01A")], cost_usd=0.0)
    merged = dims.merge_page_decision(scaffold, decision)
    by = {m["row_code"]: m for m in merged}
    assert set(by) == {"F01", "F01A", "F02"}
    assert by["F01"]["W"] == 1200 and by["F01"]["measured"] == {"vector_ok": False}, "骨架字段应保留"
    assert by["F01A"]["page"] == 2, "骨架漏拆的变体以本页记录为底新建"
    assert by["F02"]["dim_source"] == "PENDING", "视觉漏答的品番保持 PENDING 出⚠行"


def test_merge_placeholder_claimed_once_and_empty_decision_keeps_scaffold():
    scaffold = [_rec("")]  # 无文本层页占位
    merged = dims.merge_page_decision(scaffold, PageDecision(products=[_vis("F14")], cost_usd=0))
    assert [m["row_code"] for m in merged] == ["F14"], "占位记录应被视觉品番认领"
    scaffold2 = [_rec("F05")]
    merged2 = dims.merge_page_decision(scaffold2, PageDecision(products=[], cost_usd=0))
    assert merged2 == scaffold2, "视觉空手而归时保留骨架兜底"


def test_glossary_hits_scans_substrings():
    maps = {"ja→zh": {"メラミン化粧板": "防火板", "フィラー": "填缝条"}, "zh→ja": {"防火板": "メラミン化粧板"}}
    lines = dims.glossary_hits_for_text("材質：メラミン化粧板（フォーミカ）", maps)
    assert lines == ["[ja→zh] メラミン化粧板 → 防火板"]


def test_mark_duplicate_codes_and_safe_ascii():
    products = [_rec("F09", page=7), _rec("F09", page=10), _rec("F10", page=11)]
    generate._mark_duplicate_codes(products)
    assert all("重複" in p["note_jp"] for p in products if p["row_code"] == "F09")
    assert products[2]["note_jp"] == ""
    assert generate._safe_ascii("御見積書_石垣島_v1.xlsx", "quote.xlsx").endswith("v1.xlsx")
    assert generate._safe_ascii("御見積書", "quote.xlsx") == "quote.xlsx"


# ---------- 集成：handler 全管线（假 storage + 假视觉）----------

class _FakeBucket:
    def __init__(self, files: dict):
        self._files = files

    def download(self, key: str) -> bytes:
        return self._files[key]

    def upload(self, key: str, data: bytes, file_options=None):
        self._files[key] = data


class _FakeStorage:
    def __init__(self):
        self.buckets: dict[str, dict] = {}

    def from_(self, bucket: str) -> _FakeBucket:
        return _FakeBucket(self.buckets.setdefault(bucket, {}))


def _drawing_pdf_bytes() -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    page.draw_rect(fitz.Rect(100, 100, 500, 300))
    page.insert_text((550, 400), "款号：F01\n数量：1pcs\nW1200 D850 H725", fontsize=7)
    return doc.tobytes()


def _template_bytes() -> bytes:
    import io

    wb = Workbook()
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.fixture
def storage_supabase(fake_supabase):
    fake_supabase.storage = _FakeStorage()
    up = fake_supabase.storage.from_("uploads")
    up.upload("u1/quote/1/drawing.pdf", _drawing_pdf_bytes())
    up.upload("u1/quote/1/template.xlsx", _template_bytes())
    fake_supabase.table("jobs").insert({"id": "job-q1", "user_id": "u1", "feature": "quote_generate"}).execute()
    return fake_supabase


def _params(**over):
    p = {"pdf_path": "u1/quote/1/drawing.pdf", "template_path": "u1/quote/1/template.xlsx",
         "project": "测试项目", "skip_pages": []}
    p.update(over)
    return p


def test_handler_full_pipeline_offline(storage_supabase, monkeypatch):
    class _FakeClaude:
        @classmethod
        def from_env(cls):
            return cls()

    def fake_decide_page(claude, *, pageno, records, page_text, images_png, image_legend, glossary_lines):
        assert images_png, "视觉调用必须带整页渲染图"
        return PageDecision(products=[_vis(r["row_code"] or "F01") for r in records], cost_usd=0.02)

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(dims, "decide_page", fake_decide_page)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    ctx = JobContext(supabase=storage_supabase, job_id="job-q1", params=_params())
    result = generate.run(ctx)

    outputs = storage_supabase.storage.buckets["outputs"]
    xlsx_keys = [k for k in outputs if k.endswith(".xlsx")]
    assert xlsx_keys and all(k.startswith("u1/job-q1/") for k in outputs), "产物必须落在本人/本任务前缀下"
    assert result["summary"]["rows"] == 1
    assert result["summary"]["unconfirmed"] == [] and result["summary"]["missing"] == []
    assert result["summary"]["cost_usd"] == pytest.approx(0.02)
    assert result["files"][0]["display_name"].startswith("御見積書_测试项目")
    assert any("products.json" in k for k in outputs)
    # 本机无 LibreOffice → 渲染验证降级为 warning 而不是整个任务失败
    prog = storage_supabase._tables["jobs"][0]["progress"]
    assert prog >= 86


def test_handler_page_vision_failure_is_non_fatal(storage_supabase, monkeypatch):
    """单页视觉失败（如模型空输出）不拖垮整单：该页保留骨架⚠，仍出草稿 xlsx。"""
    class _FakeClaude:
        @classmethod
        def from_env(cls):
            return cls()

    def boom(claude, *, pageno, records, page_text, images_png, image_legend, glossary_lines):
        raise ValueError("模型输出里找不到 JSON 对象：''")

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(dims, "decide_page", boom)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    ctx = JobContext(supabase=storage_supabase, job_id="job-q1", params=_params())
    result = generate.run(ctx)  # 不抛异常 = 单页失败被兜住

    outputs = storage_supabase.storage.buckets["outputs"]
    assert any(k.endswith(".xlsx") for k in outputs), "即使视觉失败也要出草稿 xlsx"
    summary = result["summary"]
    assert summary["rows"] >= 1 and summary["unconfirmed"], "失败页应保留为 PENDING（⚠）"
    assert any("视觉失败" in w for w in summary["warnings"]), "应带失败页警告"


def test_handler_rejects_foreign_paths(storage_supabase):
    ctx = JobContext(supabase=storage_supabase, job_id="job-q1",
                     params=_params(pdf_path="u2/quote/1/drawing.pdf"))
    with pytest.raises(ValueError, match="本人"):
        generate.run(ctx)


def test_handler_requires_both_files(storage_supabase):
    ctx = JobContext(supabase=storage_supabase, job_id="job-q1", params=_params(template_path=""))
    with pytest.raises(ValueError, match="params 缺少"):
        generate.run(ctx)


# ---------- 回归：注册表 ----------

def test_quote_generate_registered_in_handlers():
    assert "quote_generate" in HANDLERS, "handler 必须注册进 runner.HANDLERS 才会被调度"
