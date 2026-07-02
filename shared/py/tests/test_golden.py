"""黄金文件/快照对比：把确定性输出锁进 golden/ 下的 JSON，改动若偏离即失败。

- pricing.json —— Usage.cost_usd 对一组固定 token 组合的成本（纯确定性）。
- triage_kinds.json —— 固定 PDF 的每页语向判定（稳定字段：kind / has_vector_segments）。

重新生成黄金文件：`UPDATE_GOLDEN=1 pytest tests/test_golden.py`
"""
import json
import os
import pathlib

import pytest

GOLDEN = pathlib.Path(__file__).parent / "golden"
_UPDATE = bool(os.environ.get("UPDATE_GOLDEN"))

_PRICING_CASES = [
    {},
    {"input_tokens": 1_000_000},
    {"output_tokens": 1_000_000},
    {"input_tokens": 1_000_000, "output_tokens": 1_000_000},
    {"cache_read_input_tokens": 1_000_000},
    {"cache_creation_input_tokens": 1_000_000},
    {"input_tokens": 3571, "output_tokens": 727, "cache_read_input_tokens": 6656},
]


def _load(name):
    p = GOLDEN / name
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _save(name, obj):
    GOLDEN.mkdir(exist_ok=True)
    (GOLDEN / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def test_pricing_golden():
    from claude_client import Usage

    actual = [{"tokens": c, "cost_usd": Usage(**c).cost_usd()} for c in _PRICING_CASES]
    if _UPDATE:
        _save("pricing.json", actual)
        pytest.skip("已更新 pricing.json")
    golden = _load("pricing.json")
    assert golden is not None, "缺 golden/pricing.json —— 先跑 UPDATE_GOLDEN=1 生成"
    assert len(actual) == len(golden)
    for a, g in zip(actual, golden):
        assert a["tokens"] == g["tokens"]
        assert abs(a["cost_usd"] - g["cost_usd"]) < 1e-9


def test_triage_golden(tmp_path):
    fitz = pytest.importorskip("fitz")
    from pdf_triage import triage_pdf

    doc = fitz.open()
    p0 = doc.new_page()
    p0.insert_text((72, 72), "壁面 W1200 D600 H750 収納棚 化粧板 メラミン 天板 t25 施工図")
    p0.draw_rect(fitz.Rect(40, 120, 520, 400), color=(0, 0, 0), width=1)
    doc.new_page()  # 空白
    path = str(tmp_path / "golden.pdf")
    doc.save(path)
    doc.close()

    pages = triage_pdf(path)
    actual = [
        {"page_index": p.page_index, "kind": p.kind.value, "has_vector_segments": p.has_vector_segments}
        for p in pages
    ]
    if _UPDATE:
        _save("triage_kinds.json", actual)
        pytest.skip("已更新 triage_kinds.json")
    golden = _load("triage_kinds.json")
    assert golden is not None, "缺 golden/triage_kinds.json —— 先跑 UPDATE_GOLDEN=1 生成"
    assert actual == golden
