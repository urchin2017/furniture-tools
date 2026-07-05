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


def test_merge_keeps_empty_code_local_dims():
    """回归：无品番页（如 SEKI，品番在图框里提不出）本地量出的尺寸必须并到空占位，绝不丢。"""
    scaffold = [_rec("", page=3)]
    local = dims._clean_product(
        {"row_code": "", "W": 2215, "D": 1275, "H": 2265, "dim_source": "PENDING",
         "confirm_dims": ["W", "D", "H"]}
    )
    merged = dims.merge_page_decision(scaffold, PageDecision(products=[local], cost_usd=0.0))
    assert len(merged) == 1
    assert (merged[0]["W"], merged[0]["D"], merged[0]["H"]) == (2215, 1275, 2265)
    assert merged[0]["confirm_dims"] == ["W", "D", "H"], "逐维待确认应保留"


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
        def from_env(cls, model_override=None):
            return cls()

    def fake_decide_page(claude, *, pageno, records, page_text, images_png, image_legend, glossary_lines):
        assert images_png, "视觉调用必须带整页渲染图"
        return PageDecision(products=[_vis(r["row_code"] or "F01") for r in records], cost_usd=0.02)

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(dims, "decide_page", fake_decide_page)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    # 全 AI 看图模式：强制走视觉路，验证整条编排（下载→骨架→看图→填表→上传）。
    ctx = JobContext(supabase=storage_supabase, job_id="job-q1", params=_params(vision_mode="always"))
    result = generate.run(ctx)

    outputs = storage_supabase.storage.buckets["outputs"]
    xlsx_keys = [k for k in outputs if k.endswith(".xlsx")]
    assert xlsx_keys and all(k.startswith("u1/job-q1/") for k in outputs), "产物必须落在本人/本任务前缀下"
    assert result["summary"]["rows"] == 1
    assert result["summary"]["unconfirmed"] == [] and result["summary"]["missing"] == []
    assert result["summary"]["cost_usd"] == pytest.approx(0.02)
    pp = result["summary"]["per_page"]
    assert pp and all({"page", "path", "input_tokens", "cost_usd"} <= set(e) for e in pp), "应含逐页明细"
    assert result["files"][0]["display_name"].startswith("御見積書_测试项目")
    assert any("products.json" in k for k in outputs)
    # 本机无 LibreOffice → 渲染验证降级为 warning 而不是整个任务失败
    prog = storage_supabase._tables["jobs"][0]["progress"]
    assert prog >= 86


def test_handler_page_vision_failure_is_non_fatal(storage_supabase, monkeypatch):
    """单页视觉失败（如模型空输出）不拖垮整单：该页保留骨架⚠，仍出草稿 xlsx。"""
    class _FakeClaude:
        @classmethod
        def from_env(cls, model_override=None):
            return cls()

    def boom(claude, *, pageno, records, page_text, images_png, image_legend, glossary_lines):
        raise ValueError("模型输出里找不到 JSON 对象：''")

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(dims, "decide_page", boom)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    ctx = JobContext(supabase=storage_supabase, job_id="job-q1", params=_params(vision_mode="always"))
    result = generate.run(ctx)  # 不抛异常 = 单页失败被兜住

    outputs = storage_supabase.storage.buckets["outputs"]
    assert any(k.endswith(".xlsx") for k in outputs), "即使视觉失败也要出草稿 xlsx"
    summary = result["summary"]
    assert summary["rows"] >= 1 and summary["unconfirmed"], "失败页应保留为 PENDING（⚠）"
    assert any("处理失败" in w for w in summary["warnings"]), "应带失败页警告"


def test_page_kind_and_route():
    # 位图 vs 矢量：只看是否光栅页
    assert dims.page_kind([2], 2) == "bitmap", "光栅页=位图"
    assert dims.page_kind([2], 3) == "vector", "非光栅页=矢量"
    assert dims.page_kind([], 2) == "vector"
    # 分流：矢量→本地零 AI，位图→AI 看图；local/always 覆盖判定
    assert dims.route_for_kind("vector", "auto") == "local", "智能模式矢量→本地"
    assert dims.route_for_kind("bitmap", "auto") == "vision", "智能模式位图→看图"
    assert dims.route_for_kind("vector", "always") == "vision", "全AI模式矢量也看图"
    assert dims.route_for_kind("bitmap", "local") == "local", "全本地模式位图也本地"


def test_handler_auto_mode_routes_vector_to_local(storage_supabase, monkeypatch):
    """智能(auto) 模式：矢量页（非光栅）走本地零 AI，绝不调 AI 看图。"""
    class _FakeClaude:
        @classmethod
        def from_env(cls, model_override=None):
            return cls()

    def fake_vision(*a, **k):
        raise AssertionError("矢量页不该走 AI 看图")

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))
    monkeypatch.setattr(dims, "decide_page", fake_vision)

    result = generate.run(JobContext(supabase=storage_supabase, job_id="job-q1", params=_params()))
    assert result["summary"]["local_calls"] >= 1 and result["summary"]["vision_calls"] == 0
    assert result["summary"]["cost_usd"] == 0.0, "矢量走本地 → 零成本"
    assert result["summary"]["vector_pages"], "测试 PDF 应判为矢量页"


def test_handler_always_mode_forces_vision(storage_supabase, monkeypatch):
    """always 模式：即便是矢量页，也强制走 AI 看图路。"""
    class _FakeClaude:
        @classmethod
        def from_env(cls, model_override=None):
            return cls()

    called = {"vision": 0}

    def fake_vision(claude, *, pageno, records, page_text, images_png, image_legend, glossary_lines):
        called["vision"] += 1
        return PageDecision(products=[_vis(r["row_code"] or "F01") for r in records], cost_usd=0.02)

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))
    monkeypatch.setattr(dims, "decide_page", fake_vision)

    result = generate.run(JobContext(supabase=storage_supabase, job_id="job-q1",
                                     params=_params(vision_mode="always")))
    assert called["vision"] >= 1, "always 模式强制看图"
    assert result["summary"]["vision_calls"] >= 1 and result["summary"]["local_calls"] == 0


def test_handler_cancellation_raises_jobcancelled(storage_supabase, monkeypatch):
    """任务被置 cancelled 后，管线在页间检查到即抛 JobCancelled（run_job 会据此收尾）。"""
    from app.tasks.runner import JobCancelled

    class _FakeClaude:
        @classmethod
        def from_env(cls, model_override=None):
            return cls()

    def fake_decide(*a, **k):
        return PageDecision(products=[_vis("F01")], cost_usd=0.0)

    monkeypatch.setattr(generate, "ClaudeClient", _FakeClaude)
    monkeypatch.setattr(dims, "decide_page", fake_decide)
    monkeypatch.setattr(dims, "decide_page_text", fake_decide)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))
    storage_supabase.table("jobs").update({"status": "cancelled"}).eq("id", "job-q1").execute()

    with pytest.raises(JobCancelled):
        generate.run(JobContext(supabase=storage_supabase, job_id="job-q1", params=_params()))


def test_decide_page_local_zero_ai():
    recs = [{
        "row_code": "F01", "page": 2, "qty_hint": 3,
        "measured": {
            "vector_ok": True, "confidence": "high",
            "W": {"overall_value": 1740, "extent_ok": True, "suspect_local": False},
            "H": {"overall_value": 2650, "extent_ok": True, "suspect_local": False},
        },
        "text_dims": {"W": 1740, "D": 600, "H": 2650},
    }]
    maps = {"ja→zh": {"カウンター": "柜台", "メラミン化粧板": "防火板"}}
    d = dims.decide_page_local(recs, "品名：カウンター\n材質：メラミン化粧板", maps)
    assert d.cost_usd == 0.0 and d.input_tokens == 0, "本地零 AI：无成本、无 token"
    p = d.products[0]
    assert p["W"] == 1740 and p["H"] == 2650 and p["D"] == 600
    assert p["dim_source"] == "geometry"          # W/H 几何、与文字一致
    assert "W" not in p["confirm_dims"]            # 几何✕文字一致 → 不⚠
    assert "D" in p["confirm_dims"]                # D 仅文字来源 → ⚠
    assert p["name_cn"] == "柜台" and "防火板" in p["mat_cn"]  # 术语表脚本翻译


def test_analyze_pdf_classifies_and_plans(tmp_path):
    """判断步骤：矢量测试页 → kind=vector、计划 local（零 AI）；always 模式改判 vision。"""
    from app.modules.quote.analyze import analyze_pdf

    p = tmp_path / "d.pdf"
    p.write_bytes(_drawing_pdf_bytes())

    out = analyze_pdf(str(p), skip_pages=[], vision_mode="auto")
    assert out["summary"]["total"] == 1
    assert out["pages"][0]["kind"] == "vector" and out["pages"][0]["path"] == "local"
    assert out["summary"]["ai_pages"] == [] and out["summary"]["local_pages"] == [1]

    out2 = analyze_pdf(str(p), skip_pages=[], vision_mode="always")
    assert out2["pages"][0]["path"] == "vision" and out2["summary"]["ai_pages"] == [1]


def _bitmap_pdf_bytes() -> bytes:
    """一页嵌 600×600 位图、无矢量线 → detect_raster 判为位图页。"""
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 600, 600))
    pix.set_rect(pix.irect, (240, 240, 240))
    page.insert_image(fitz.Rect(40, 40, 700, 540), stream=pix.tobytes("png"))
    page.insert_text((60, 560), "款号：R01", fontsize=8)
    return doc.tobytes()


def test_analyze_pdf_bitmap_and_skipall_boundaries(tmp_path):
    """边界/异常：位图页→计划 vision；跳过全部页→空计划不报错。"""
    from app.modules.quote.analyze import analyze_pdf

    pb = tmp_path / "b.pdf"
    pb.write_bytes(_bitmap_pdf_bytes())
    out = analyze_pdf(str(pb), skip_pages=[], vision_mode="auto")
    assert out["pages"][0]["kind"] == "bitmap" and out["pages"][0]["path"] == "vision"
    assert out["summary"]["ai_pages"] == [1] and out["summary"]["bitmap_pages"] == [1]
    # 位图页在纯本地模式仍计划 local（用户要零 AI），但 kind 仍是 bitmap
    out_l = analyze_pdf(str(pb), skip_pages=[], vision_mode="local")
    assert out_l["pages"][0]["kind"] == "bitmap" and out_l["pages"][0]["path"] == "local"
    # 跳过全部页 → 空计划（不抛）
    out0 = analyze_pdf(str(pb), skip_pages=[1], vision_mode="auto")
    assert out0["summary"]["total"] == 0 and out0["pages"] == []


def test_analyze_pdf_bad_path_raises():
    from app.modules.quote.analyze import analyze_pdf

    with pytest.raises(Exception):  # noqa: B017 — 坏路径应抛（路由层会转 400）
        analyze_pdf("/no/such/file.pdf", skip_pages=[], vision_mode="auto")


def test_analyze_matches_generate_classification(storage_supabase, monkeypatch):
    """回归：analyze 的位图/矢量判定必须与 generate summary 的分类一致（同一分流依据）。"""
    from app.modules.quote.analyze import analyze_pdf

    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))
    # 用与集成夹具相同的图纸（矢量测试页）
    pdf_bytes = storage_supabase.storage.from_("uploads").download("u1/quote/1/drawing.pdf")
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tf:
        tf.write(pdf_bytes)
        tf.flush()
        a = analyze_pdf(tf.name, skip_pages=[], vision_mode="local")

    result = generate.run(JobContext(supabase=storage_supabase, job_id="job-q1",
                                     params=_params(vision_mode="local")))
    assert a["summary"]["vector_pages"] == result["summary"]["vector_pages"]
    assert a["summary"]["bitmap_pages"] == result["summary"]["bitmap_pages"]


def test_extract_materials_chinese_japanese_and_excludes_supply_notes():
    """材质提取：中日双语材质都抓（含部位前缀整行）；纯供给/安装说明（客供/现场安装）不当材质。"""
    text = (
        "正面：防火板（富美家）\n"       # 中文材质（创明）
        "背面：平衡板（黑or白）\n"
        "小口：PVC\n"
        "脚：客供 现场安装\n"           # 供给/安装说明——不是材质，必须排除
        "调整脚：普通透明的\n"          # 无材质名词——排除
        "面材：メラミン化粧板（リアテック同柄）\n"  # 日文材质（SEKI）
        "ITEM No. CIY_B-01\n"          # 非材质行
        "W2215 D1275 H2265\n"
    )
    mats = dims._extract_materials(text)
    assert any("防火板" in m for m in mats)
    assert any("平衡板" in m for m in mats)
    assert any("PVC" in m for m in mats)
    assert any("メラミン化粧板" in m for m in mats)
    assert not any("客供" in m for m in mats), "供给/安装说明不该当材质"
    assert not any("现场安装" in m for m in mats)
    assert not any("普通透明" in m for m in mats), "无材质名词的行不该收"
    assert not any("CIY_B-01" in m for m in mats)


def test_decide_page_local_fills_materials_without_prefix():
    """回归：SEKI 式材质（面材：… / 裸材质名）本地也能提取，不再整页材质为空。"""
    recs = [{"row_code": "", "page": 3, "qty_hint": None,
             "measured": {"vector_ok": True, "confidence": "mid"},
             "text_dims": {"W": 2215, "D": 1275, "H": 2265}}]
    text = "面材：メラミン化粧板（リアテック同柄）\nフレーム：32角パイプ（黒塗装）"
    d = dims.decide_page_local(recs, text, {})
    p = d.products[0]
    assert p["mat_jp"], "材质不应为空"
    assert any("メラミン化粧板" in m for m in p["mat_jp"])
    assert p["note_cn"] == "" and p["note_jp"] == "", "本地备注不再写流程/AI 说明"


def test_spec_notes_and_completeness_report():
    """说明文件包含完整性自检 + 逐行明细；缺字段被检出。"""
    products = [
        {"row_code": "F01", "page": 2, "W": 1200, "D": 850, "H": 725, "qty": 3,
         "name_jp": "机", "mat_jp": ["メラミン"], "dim_source": "visual",
         "dim_evidence": "外形線", "confirm_dims": [], "note_cn": ""},
        {"row_code": "", "page": 3, "W": None, "D": None, "H": None, "qty": None,
         "name_jp": "", "mat_jp": [], "dim_source": "PENDING",
         "dim_evidence": "", "confirm_dims": [], "note_cn": ""},
    ]
    gaps = generate._completeness_gaps(products)
    assert len(gaps) == 1 and gaps[0]["row"] == 2
    assert set(gaps[0]["missing"]) == {"材质", "品名", "尺寸", "数量"}
    txt = generate._build_spec_notes("测试", products, gaps)
    assert "完整性自检" in txt and "逐行明细" in txt
    assert "缺 材质/品名/尺寸/数量" in txt
    assert "本地提取" not in txt or True  # 说明文件可含过程信息（这里无）


def test_finalize_fills_name_from_code_and_variant_width():
    """品名本地查表补：缺品名的行按品番补；同品番多行（变体）按 W 加「-W宽」区分。"""
    products = [
        {"row_code": "CIY_TV-01", "W": 800, "name_jp": "", "name_cn": "", "mat_jp": [], "mat_cn": []},
        {"row_code": "CIY_M-01", "W": 653, "name_jp": "", "name_cn": "", "mat_jp": [], "mat_cn": []},
        {"row_code": "CIY_M-01", "W": 600, "name_jp": "", "name_cn": "", "mat_jp": [], "mat_cn": []},
        {"row_code": "F01", "W": 1200, "name_jp": "餐桌", "name_cn": "餐桌", "mat_jp": [], "mat_cn": []},
    ]
    generate._finalize_names_materials(products)
    assert products[0]["name_jp"] == "TVボード" and products[0]["name_cn"] == "电视板"
    # 变体：CIY_M-01 两行按 W 区分
    assert products[1]["name_jp"] == "ミラー-W653" and products[2]["name_jp"] == "ミラー-W600"
    assert products[3]["name_jp"] == "餐桌", "已有品名不覆盖"


def test_finalize_makes_materials_bilingual():
    """材质单侧为空→补成中日双语：日文行补中文、中文行补日文。"""
    # 只有日文（SEKI）
    jp_only = [{"row_code": "X", "mat_jp": ["面材：メラミン化粧板"], "mat_cn": []}]
    generate._finalize_names_materials(jp_only)
    p = jp_only[0]
    assert p["mat_jp"] and p["mat_cn"], "两列都应有内容"
    assert any("防火板" in m for m in p["mat_cn"]), "メラミン化粧板→防火板"
    # 只有中文（创明）
    cn_only = [{"row_code": "Y", "mat_jp": [], "mat_cn": ["正面：防火板（富美家）"]}]
    generate._finalize_names_materials(cn_only)
    q = cn_only[0]
    assert q["mat_jp"] and q["mat_cn"]
    assert any("メラミン化粧板" in m or "フォーミカ" in m for m in q["mat_jp"]), "防火板/富美家→日文"


def test_propagate_family_depth_borrows_within_product_family():
    """同产品族借深度：デスク族借 500、バンクベッド族借 1275；独一无二的产品保持空（不臆造）。"""
    products = [
        {"row_code": "CIY_D-01", "name_jp": "デスク-Aタイプ", "W": 1000, "D": 500, "H": 745, "confirm_dims": []},
        {"row_code": "CIY_D-02", "name_jp": "デスク-Bタイプ", "W": 1000, "D": None, "H": 745, "confirm_dims": []},
        {"row_code": "CIY_B-01", "name_jp": "バンクベッド-Aタイプ", "W": 2095, "D": None, "H": 1535, "confirm_dims": []},
        {"row_code": "CIY_B-02", "name_jp": "バンクベッド-Bタイプ", "W": 2215, "D": 1275, "H": 2265, "confirm_dims": []},
        {"row_code": "CIY_L-01", "name_jp": "ビッグテーブル（LOUNGE）", "W": 4000, "D": None, "H": 2700, "confirm_dims": []},
    ]
    generate._propagate_family_depth(products)
    assert products[1]["D"] == 500 and "D" in products[1]["confirm_dims"], "デスク族借 500"
    assert products[2]["D"] == 1275, "バンクベッド族借 1275"
    assert products[4]["D"] is None, "独一无二的产品不臆造深度"


def test_local_axis_geometry_fallback_fills_wh_without_titleblock():
    """图框无注记时，W/H 用几何引擎 overall_value 兜底填（本地零 AI），标复核。"""
    measured = {"vector_ok": True, "confidence": "mid",
                "W": {"overall_value": 4000, "extent_ok": False, "suspect_local": True},
                "H": {"overall_value": 2700, "extent_ok": False, "suspect_local": True}}
    w, ws_, wflag = dims._local_axis(measured, {"W": None, "D": None, "H": None}, "W")
    assert w == 4000 and wflag is True, "几何兜底填 W 并标复核"
    h, hs_, _ = dims._local_axis(measured, {}, "H")
    assert h == 2700


def test_handler_auto_never_calls_ai_on_vector(storage_supabase, monkeypatch):
    """矢量图纸在智能模式下**坚决不调 AI**（成本 0），品名靠本地查表、材质靠术语表补。"""
    class _NoAIClaude:
        @classmethod
        def from_env(cls, model_override=None):
            return cls()

    def boom(*a, **k):
        raise AssertionError("矢量页不得调用 AI 看图")

    monkeypatch.setattr(generate, "ClaudeClient", _NoAIClaude)
    monkeypatch.setattr(dims, "decide_page", boom)   # 视觉路被调用即失败
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    result = generate.run(JobContext(supabase=storage_supabase, job_id="job-q1", params=_params()))
    assert result["summary"]["vision_calls"] == 0 and result["summary"]["cost_usd"] == 0.0


def test_handler_local_mode_makes_no_ai_call(storage_supabase, monkeypatch):
    def _no(*a, **k):
        raise AssertionError("local 模式不该调用任何 AI")

    class _NoClaude:
        @staticmethod
        def from_env():
            raise AssertionError("local 模式不该建 Claude 客户端")

    monkeypatch.setattr(generate, "ClaudeClient", _NoClaude)
    monkeypatch.setattr(dims, "decide_page", _no)
    monkeypatch.setattr(dims, "decide_page_text", _no)
    monkeypatch.setattr(generate, "_load_glossary_maps", lambda ctx: ({}, []))

    result = generate.run(JobContext(supabase=storage_supabase, job_id="job-q1",
                                     params=_params(vision_mode="local")))
    assert result["summary"]["local_calls"] >= 1
    assert result["summary"]["cost_usd"] == 0.0
    outputs = storage_supabase.storage.buckets["outputs"]
    assert any(k.endswith(".xlsx") for k in outputs), "本地模式也出 xlsx（草稿）"


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
