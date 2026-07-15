#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
drawing_probe.py —— 图纸"确定性读取"最小验证脚本
用法:
    python3 drawing_probe.py 你的图纸.pdf
    python3 drawing_probe.py 你的图纸.pdf 2      # 只看第 2 页
输出:每页报告 —— 矢量/扫描判定、线条统计、外形候选框、尺寸文字↔线条关联。
依赖: pip install pymupdf
"""

import sys
import re
import fitz  # PyMuPDF

DIM_RE = re.compile(r"^[WHDwhdØφ]?\s*[=＝]?\s*\d{2,5}(\.\d+)?\s*(mm|MM|㎜)?$")
FLAT_TOL = 1.5
NEAR_TOL = 25


def classify_page(words, drawings):
    n_paths = len(drawings)
    n_words = len(words)
    if n_paths == 0 and n_words <= 2:
        return "扫描位图/纯图像(无文本层,建议走 OpenCV+OCR 或 AI 视觉)"
    if n_paths == 0:
        return "有文字但无矢量线条(可能是纯文本页或图形被压成图片)"
    return "矢量图(有线条几何,可做确定性读取)"


def collect_segments(drawings):
    h_lines, v_lines = [], []
    rects = []
    for path in drawings:
        for item in path["items"]:
            op = item[0]
            if op == "l":
                p1, p2 = item[1], item[2]
                dx, dy = abs(p2.x - p1.x), abs(p2.y - p1.y)
                if dy <= FLAT_TOL and dx > FLAT_TOL:
                    h_lines.append((p1.x, p1.y, p2.x, p2.y, dx))
                elif dx <= FLAT_TOL and dy > FLAT_TOL:
                    v_lines.append((p1.x, p1.y, p2.x, p2.y, dy))
            elif op == "re":
                r = item[1]
                rects.append(r)
        if path.get("rect") is not None and path.get("closePath"):
            rects.append(path["rect"])
    return h_lines, v_lines, rects


def numeric_tokens(words):
    toks = []
    for (x0, y0, x1, y1, text, *_rest) in words:
        t = text.strip()
        if DIM_RE.match(t):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            toks.append((t, cx, cy, (x0, y0, x1, y1)))
    return toks


def associate(toks, h_lines, v_lines):
    results = []
    for (t, cx, cy, _bbox) in toks:
        best = None
        for (x0, y0, x1, y1, ln) in h_lines:
            if min(x0, x1) - NEAR_TOL <= cx <= max(x0, x1) + NEAR_TOL:
                d = abs(cy - y0)
                if d <= NEAR_TOL and (best is None or d < best[0]):
                    best = (d, "宽度(横向)", ln)
        for (x0, y0, x1, y1, ln) in v_lines:
            if min(y0, y1) - NEAR_TOL <= cy <= max(y0, y1) + NEAR_TOL:
                d = abs(cx - x0)
                if d <= NEAR_TOL and (best is None or d < best[0]):
                    best = (d, "高度(纵向)", ln)
        if best:
            results.append((t, best[1], round(best[2], 1), round(best[0], 1)))
        else:
            results.append((t, "未关联到尺寸线(可能是内部标注/注记)", None, None))
    return results


def probe_page(page, page_no):
    words = page.get_text("words")
    drawings = page.get_drawings()
    print(f"\n{'='*60}\n第 {page_no} 页  尺寸 {page.rect.width:.0f}×{page.rect.height:.0f}pt")
    print(f"判定: {classify_page(words, drawings)}")
    print(f"矢量路径数: {len(drawings)}   文字数: {len(words)}")
    h_lines, v_lines, rects = collect_segments(drawings)
    print(f"水平线: {len(h_lines)} 条   垂直线: {len(v_lines)} 条   矩形: {len(rects)} 个")
    if rects:
        biggest = max(rects, key=lambda r: r.width * r.height)
        print(f"外形候选框(最大矩形): {biggest.width:.0f}×{biggest.height:.0f}pt "
              f"@ ({biggest.x0:.0f},{biggest.y0:.0f})  ← 页面点数,非真实mm")
    toks = numeric_tokens(words)
    if toks:
        print(f"\n识别到 {len(toks)} 个尺寸数字,关联结果:")
        for (t, direction, line_len, dist) in associate(toks, h_lines, v_lines):
            extra = f"  (贴合尺寸线长≈{line_len}pt, 间距{dist}pt)" if line_len else ""
            print(f"  • “{t}”  →  {direction}{extra}")
    else:
        print("\n未识别到尺寸数字(可能是扫描图,或数字格式需调 DIM_RE)")


def main():
    if len(sys.argv) < 2:
        print("用法: python3 drawing_probe.py 图纸.pdf [页码]")
        sys.exit(1)
    path = sys.argv[1]
    only = int(sys.argv[2]) - 1 if len(sys.argv) > 2 else None
    doc = fitz.open(path)
    for i, page in enumerate(doc):
        if only is not None and i != only:
            continue
        probe_page(page, i + 1)
    print(f"\n{'='*60}\n完成。矢量页 → 关联可直接信;扫描页 → 需 OCR/AI 兜底。")


if __name__ == "__main__":
    main()
