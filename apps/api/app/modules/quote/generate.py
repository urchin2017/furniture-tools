"""quote_generate 的 JobHandler：图纸 PDF + Excel 模板 → 御見積書。

编排 skill v5 四步管线（机械脚本在 shared/py/skills/drawing_to_quotation）：
  ① build_scaffold（骨架+光栅判定） ② 视觉定外形尺寸（dims.py → complete_vision）
  ③ fill_quote_build（填模板） ④ render_xlsx（LibreOffice 渲染目视验证图）

输入 params（前端建任务时给）：
  pdf_path / template_path —— uploads 桶内 key，必须以 "<user_id>/" 开头
  project(str) / skip_pages(list[int], 默认[1]=封面) / start_row(18) / last_row(50)
  require_visual(bool, 默认 False=允许出带⚠草稿)

输出 output_files（写回 jobs 表）：outputs 桶文件清单 + 尺寸摘要 + 成本。
"""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import fitz

from app.config import get_settings  # noqa: F401  (触发 shared/py 加入 sys.path，须在下面 import 之前)

from claude_client import ClaudeClient
from glossary import GlossaryClient
from netretry import with_retry
from skills.drawing_to_quotation import build_scaffold, fill_quote_build, render_xlsx

from app.tasks.runner import JobCancelled

from . import dims

_CONTENT_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".png": "image/png",
    ".json": "application/json",
    ".pdf": "application/pdf",
}


def _content_type(path: str) -> str:
    return _CONTENT_TYPES.get(os.path.splitext(path)[1].lower(), "application/octet-stream")


def _safe_ascii(name: str, fallback: str) -> str:
    """storage 对象 key 只用 ASCII（非 ASCII key 在 Supabase storage 上不可靠）。"""
    s = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return s or fallback


def _get_user_id(ctx) -> str:
    rows = with_retry(
        lambda: ctx.supabase.table("jobs").select("user_id").eq("id", ctx.job_id).limit(1).execute().data,
        desc="查任务归属",
    )
    if not rows:
        raise RuntimeError(f"jobs 表里找不到任务 {ctx.job_id}")
    return rows[0]["user_id"]


def _download(ctx, bucket: str, key: str, dest: str) -> str:
    data = with_retry(lambda: ctx.supabase.storage.from_(bucket).download(key), desc=f"下载 {key}")
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def _upload(ctx, bucket: str, key: str, local_path: str) -> dict[str, Any]:
    with open(local_path, "rb") as f:
        data = f.read()
    with_retry(
        lambda: ctx.supabase.storage.from_(bucket).upload(
            key, data, file_options={"content-type": _content_type(local_path), "upsert": "true"}
        ),
        desc=f"上传 {key}",
    )
    return {
        "bucket": bucket,
        "path": key,
        "name": os.path.basename(local_path),
        "content_type": _content_type(local_path),
        "size": len(data),
    }


def _load_glossary_maps(ctx) -> tuple[dict[str, dict[str, str]], list[str]]:
    """报价用双向术语提示（日⇄中）。术语表挂了不阻塞管线，只记 warning。"""
    warnings: list[str] = []
    maps: dict[str, dict[str, str]] = {}
    try:
        g = GlossaryClient(ctx.supabase)
        maps["ja→zh"] = with_retry(lambda: g.load_map("ja", "zh"), desc="载入术语表 ja→zh")
        maps["zh→ja"] = with_retry(lambda: g.load_map("zh", "ja"), desc="载入术语表 zh→ja")
    except Exception as exc:  # noqa: BLE001 — 术语表不可用只降级，不让任务失败
        warnings.append(f"术语表加载失败（翻译无术语提示）：{exc}")
        maps = {}
    return maps, warnings


def _mark_duplicate_codes(products: list[dict[str, Any]]) -> None:
    """同一品番出现在多页（如 F09 既是 Counter 又是 Shelf-02）→ 两行都保留＋备考报警。"""
    counts = Counter(p.get("row_code") for p in products if p.get("row_code"))
    for p in products:
        code = p.get("row_code")
        if code and counts[code] > 1 and "重複" not in (p.get("note_jp") or ""):
            p["note_jp"] = ((p.get("note_jp") or "") + f"\n品番{code}重複使用・要確認").strip()
            p["note_cn"] = ((p.get("note_cn") or "") + f"\n品番{code}重复使用·待确认").strip()


_KANA_RE = re.compile(r"[぀-ヿ]")  # 平/片假名 → 判定日文行


def _translate_terms(line: str, terms: dict[str, str]) -> str:
    """按术语表逐词替换（长词优先）翻译一行；未命中的片段保留原文。"""
    out = line or ""
    for k in sorted(terms, key=len, reverse=True):
        if k and k in out:
            out = out.replace(k, terms[k])
    return out


def _bilingual_materials(jp_lines, cn_lines) -> tuple[list[str], list[str]]:
    """把材质整理成日/中两列都齐：日文行→补中列译文，中文行→补日列译文。缺侧用内置术语表兜底。"""
    from .product_names import TERMS, TERMS_ZH2JP

    seen: list[str] = []
    for x in list(jp_lines or []) + list(cn_lines or []):
        x = str(x).strip()
        if x and x not in seen:
            seen.append(x)
    jp: list[str] = []
    cn: list[str] = []
    for ln in seen:
        if _KANA_RE.search(ln):          # 日文行
            jp.append(ln)
            cn.append(_translate_terms(ln, TERMS))
        else:                             # 中文/英文/符号行
            cn.append(ln)
            jp.append(_translate_terms(ln, TERMS_ZH2JP))
    return jp, cn


def _finalize_names_materials(products: list[dict[str, Any]]) -> None:
    """出行前本地补全（零 AI）：① 品名缺则按品番查表补，同品番变体按 W 加「-W宽」区分；
    ② 材质一侧为空时用内置术语表补成中日双语。AI 已给出的品名/双语材质不覆盖。"""
    from .product_names import PRODUCT_NAMES

    counts = Counter(p.get("row_code") for p in products if p.get("row_code"))
    for p in products:
        code = p.get("row_code") or ""
        if not str(p.get("name_jp") or "").strip() and not str(p.get("name_cn") or "").strip():
            hit = PRODUCT_NAMES.get(code)
            if hit:
                jp, cn = hit
                if counts[code] > 1 and p.get("W"):   # 同品番尺寸变体 → 附 -W{宽} 区分
                    jp, cn = f"{jp}-W{p['W']}", f"{cn}-W{p['W']}"
                p["name_jp"], p["name_cn"] = jp, cn
        mj, mc = p.get("mat_jp") or [], p.get("mat_cn") or []
        if mj and not mc:                 # 只有日文 → 补中文
            p["mat_jp"], p["mat_cn"] = _bilingual_materials(mj, [])
        elif mc and not mj:               # 只有中文 → 补日文
            p["mat_jp"], p["mat_cn"] = _bilingual_materials([], mc)


_NAME_SUFFIX_RE = re.compile(r"[-‐](?:[ＡＢＣA-C]?タイプ|[A-C]型|W\d+).*$")


def _propagate_family_depth(products: list[dict[str, Any]]) -> None:
    """同一产品族（同品名，去掉 -Aタイプ/-W宽 后缀）内，某行缺 D → 借同族已知的 D
    （同产品线通常同深度，如 デスク-A/B/C 都 D500）。纯本地推断、标复核，不臆造任意数。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for p in products:
        base = _NAME_SUFFIX_RE.sub("", str(p.get("name_jp") or "").strip())
        if base:
            groups.setdefault(base, []).append(p)
    for grp in groups.values():
        donor = next((q.get("D") for q in grp if q.get("D") not in (None, "", 0)), None)
        if donor is None:
            continue
        for p in grp:
            if p.get("D") in (None, "", 0):
                p["D"] = donor
                cd = set(p.get("confirm_dims") or [])
                cd.add("D")
                p["confirm_dims"] = [k for k in ("W", "D", "H") if k in cd]


def _missing_fields(p: dict[str, Any]) -> list[str]:
    """一条记录缺哪些必填字段（材质/品名/尺寸/数量）。"""
    miss = []
    if not (p.get("mat_jp") or p.get("mat_cn")):
        miss.append("材质")
    if not (p.get("name_jp") or p.get("name_cn")):
        miss.append("品名")
    if any(p.get(k) in (None, "", 0) for k in ("W", "D", "H")):
        miss.append("尺寸")
    if p.get("qty") in (None, "", 0):
        miss.append("数量")
    return miss


def _completeness_gaps(products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """出单前自检：逐行列出仍缺的必填字段（供说明文件 + 前端提示，绝不塞进 Excel）。"""
    gaps = []
    for i, p in enumerate(products, 1):
        miss = _missing_fields(p)
        if miss:
            gaps.append({"row": i, "row_code": p.get("row_code") or "(空品番)",
                         "page": p.get("page"), "missing": miss})
    return gaps


def _build_spec_notes(project: str, products: list[dict[str, Any]],
                      completeness: list[dict[str, Any]]) -> str:
    """说明文件正文：AI/本地提取过程信息 + 逐行复核提示 + 完整性自检。**内容不进 Excel。**"""
    L = [f"御見積書 生成说明 · {project or '(未命名)'}",
         "本文件记录提取过程信息与逐项复核提示；这些内容不进 Excel 报价单，仅供内部核对。", ""]
    L.append(f"一、完整性自检：共 {len(products)} 行。" +
             (f"以下 {len(completeness)} 行仍有缺项，需人工补齐：" if completeness else "所有必填字段（材质/品名/尺寸/数量）均已填写。"))
    for g in completeness:
        L.append(f"    第{g['row']}行 {g['row_code']}（第{g['page']}页）：缺 {'/'.join(g['missing'])}")
    L += ["", "二、逐行明细（尺寸来源 / 需复核维 / 依据 / 提取备注）："]
    for i, p in enumerate(products, 1):
        code = p.get("row_code") or "(空品番)"
        conf = "/".join(p.get("confirm_dims") or []) or "无"
        ev = (p.get("dim_evidence") or "").strip() or "—"
        note = " ".join(x for x in [(p.get("note_jp") or "").strip(),
                                    (p.get("note_cn") or "").strip()] if x) or "—"
        mats = "、".join(p.get("mat_jp") or []) or "—"
        L.append(f"    第{i}行 {code} p{p.get('page')}｜W={p.get('W')} D={p.get('D')} "
                 f"H={p.get('H')} 数量={p.get('qty')}｜材质={mats}｜来源={p.get('dim_source')} "
                 f"需复核={conf}｜依据={ev}｜备注={note}")
    return "\n".join(L)


def run(ctx) -> dict[str, Any]:
    params = ctx.params or {}
    pdf_key = params.get("pdf_path") or ""
    template_key = params.get("template_path") or ""
    project = str(params.get("project") or "")
    raw_skip = params.get("skip_pages")
    skip_pages = [int(x) for x in raw_skip] if raw_skip is not None else [1]  # 默认跳封面页
    start_row = int(params.get("start_row") or 18)
    last_row = int(params.get("last_row") or 50)
    require_visual = bool(params.get("require_visual"))

    if not pdf_key or not template_key:
        raise ValueError("params 缺少 pdf_path / template_path")
    user_id = _get_user_id(ctx)
    for key in (pdf_key, template_key):
        if not str(key).startswith(f"{user_id}/"):
            raise ValueError("非法文件路径：必须位于本人 uploads 目录下")

    workdir = tempfile.mkdtemp(prefix="quote_generate_")
    try:
        pdf_local = _download(ctx, "uploads", pdf_key, os.path.join(workdir, "drawing.pdf"))
        template_local = _download(ctx, "uploads", template_key, os.path.join(workdir, "template.xlsx"))
        ctx.report_progress(8)

        # ① 骨架 + 光栅判定 + 整页图
        json_path = os.path.join(workdir, "products.json")
        payload = build_scaffold(
            pdf_local, json_path, img_dir=os.path.join(workdir, "pages"),
            dpi=150, skip_pages=skip_pages, project=project,
        )
        products: list[dict[str, Any]] = payload["products"]
        raster_pages: list[int] = payload.get("raster_pages", [])
        ctx.report_progress(15)

        # ② 定外形尺寸。核心分流原则：**先判位图还是矢量，再决定用不用 AI**。
        #    vision_mode 三档：
        #    local  = 一律本地零 AI（几何+术语表，不调 Anthropic、不需 API key）；
        #    auto   = 智能（默认·推荐）：**矢量页→本地零 AI（几何可读）；位图页→AI 看图（本地读不了）**；
        #    always = 一律 AI 看图（最准最贵）。
        #    AI 看图只读图面尺寸线、不读文字注记（客户手填尺寸常有误）。
        #    多页并行（QUOTE_VISION_CONCURRENCY，默认4）；system prompt 逐页复用走 ephemeral 缓存。
        maps, warnings = _load_glossary_maps(ctx)
        pages = sorted({p["page"] for p in products})
        vmode = str(params.get("vision_mode") or os.environ.get("QUOTE_VISION_MODE", "auto")).lower()
        # 模型选择（前端下拉）：仅接受白名单内的模型 id，否则回退 .env 默认（防注入/打错）。
        _allowed_models = {"claude-opus-4-8", "claude-sonnet-5", "claude-haiku-4-5-20251001"}
        _model_sel = str(params.get("model") or "")
        _model_sel = _model_sel if _model_sel in _allowed_models else None
        # 纯本地模式不碰 Anthropic：连 key 都不需要，客户端也不建。
        claude = None if vmode == "local" else ClaudeClient.from_env(_model_sel)
        cost_usd = 0.0
        in_tok = 0
        out_tok = 0
        cache_read_tok = 0
        cache_write_tok = 0
        model = ""
        vision_dir = os.path.join(workdir, "vision")

        def _decide_one(pageno: int):
            # 每线程独立开一份 fitz doc：PyMuPDF 的 Document 非线程安全，不能跨线程共享。
            d = fitz.open(pdf_local)
            try:
                recs = [p for p in products if p["page"] == pageno]
                page_text = d[pageno - 1].get_text()
                gl_lines = dims.glossary_hits_for_text(page_text, maps)
                # 先判位图/矢量，再按模式决定用不用 AI（矢量→本地，位图→AI 看图）。
                kind = dims.page_kind(raster_pages, pageno)
                path = dims.route_for_kind(kind, vmode)
                try:
                    if path == "vision":
                        # 位图页：本地几何量不出，交 AI 看图——只读图面尺寸线、不读文字注记。
                        images, legend = dims.render_vision_images(d, pageno, vision_dir)
                        decision = dims.decide_page(
                            claude, pageno=pageno, records=recs, page_text=page_text,
                            images_png=images, image_legend=legend, glossary_lines=gl_lines,
                        )
                    else:  # local：矢量页**纯本地、零 AI**（几何 + 图框品番/数量/尺寸/品名查表 + 术语表）
                        decision = dims.decide_page_local(recs, page_text, maps)
                except Exception as exc:  # noqa: BLE001
                    # 单页处理失败不拖垮整单：该页返回空决策，走⚠兜底（保留骨架、标 PENDING）。
                    _lbl = {"vision": "看图", "local": "本地"}.get(path, "处理")
                    decision = dims.PageDecision(
                        products=[], cost_usd=0.0,
                        warnings=[f"第 {pageno} 页{_lbl}处理失败，已跳过、保留骨架待人工核对：{exc}"],
                    )
                return pageno, recs, decision, path, kind
            finally:
                d.close()

        n_pages = len(pages)
        workers = max(1, min(int(os.environ.get("QUOTE_VISION_CONCURRENCY", "4")), n_pages or 1))
        decisions: dict[int, tuple[list[dict[str, Any]], Any]] = {}
        per_page: list[dict[str, Any]] = []
        n_vision = 0
        n_local = 0
        bitmap_pages: list[int] = []
        vector_pages: list[int] = []
        done = 0
        ex = ThreadPoolExecutor(max_workers=workers)
        try:
            futs = {ex.submit(_decide_one, pn): pn for pn in pages}
            for fut in as_completed(futs):
                pageno, recs, decision, path, kind = fut.result()
                decisions[pageno] = (recs, decision)
                if path == "vision":
                    n_vision += 1
                else:
                    n_local += 1
                (bitmap_pages if kind == "bitmap" else vector_pages).append(pageno)
                cost_usd += decision.cost_usd
                in_tok += decision.input_tokens
                out_tok += decision.output_tokens
                cache_read_tok += decision.cache_read_input_tokens
                cache_write_tok += decision.cache_creation_input_tokens
                model = decision.model or model
                # 逐页 token/成本明细：让前端能看「每页（单次）」而非只有整单汇总。
                per_page.append({
                    "page": pageno,
                    "kind": kind,
                    "path": path,
                    "input_tokens": decision.input_tokens,
                    "output_tokens": decision.output_tokens,
                    "cost_usd": round(decision.cost_usd, 4),
                })
                done += 1
                ctx.report_progress(15 + int(60 * done / n_pages))
                if ctx.is_cancelled():  # 用户中途取消 → 立即停下（未开始的页丢弃、进行中的自然结束）
                    raise JobCancelled()
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        per_page.sort(key=lambda x: x["page"])
        bitmap_pages.sort()
        vector_pages.sort()

        # 按页序合并，保证 Excel 行序稳定（与并行完成先后无关）
        merged_all: list[dict[str, Any]] = []
        for pn in pages:
            recs, decision = decisions[pn]
            warnings.extend(decision.warnings)
            merged_all.extend(dims.merge_page_decision(recs, decision))

        products = merged_all
        _finalize_names_materials(products)  # 本地补品名（品番查表）+ 材质中日双语（零 AI）
        _propagate_family_depth(products)    # 同产品族借深度 D（本地推断，零 AI）
        _mark_duplicate_codes(products)
        payload["products"] = products
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        ctx.report_progress(78)

        # ③ 填 Excel 模板（视觉确认闸门在 fill_quote 里）
        today = datetime.date.today().isoformat()
        display_name = f"御見積書_{project or '報価'}_v1_{today}.xlsx"
        out_xlsx = os.path.join(workdir, display_name)
        fill_summary = fill_quote_build(
            pdf_local, template_local, json_path, out_xlsx, project,
            start_row, last_row, require_visual,
        )
        ctx.report_progress(86)

        # ④ 渲染目视验证（需 LibreOffice；本机没有 soffice 时降级跳过）
        check_pngs: list[str] = []
        try:
            check_pngs = render_xlsx(out_xlsx, os.path.join(workdir, "check"),
                                     area=f"A1:N{last_row + 3}")
        except Exception as exc:  # noqa: BLE001 — 渲染验证是加分项，失败不吞掉成品
            warnings.append(f"渲染验证跳过（LibreOffice 不可用或转换失败）：{exc}")
        ctx.report_progress(93)

        # 生成前最终自检：逐行核对必填字段（材质/品名/尺寸/数量）是否有遗漏，写进说明文件。
        completeness = _completeness_gaps(products)
        # 说明文件：AI/本地提取的过程信息、逐项复核提示——**这些不进 Excel**，只放这里。
        notes_name = f"说明_{project or '報価'}_{today}.txt"
        notes_path = os.path.join(workdir, notes_name)
        with open(notes_path, "w", encoding="utf-8") as f:
            f.write(_build_spec_notes(project, products, completeness))

        # 上传 outputs 桶（key 用 ASCII，中文名放 display_name 由前端下载时还原）
        prefix = f"{user_id}/{ctx.job_id}"
        files = [_upload(ctx, "outputs", f"{prefix}/{_safe_ascii(display_name, 'quote.xlsx')}", out_xlsx)]
        files[0]["display_name"] = display_name
        for png in check_pngs:
            files.append(_upload(ctx, "outputs", f"{prefix}/check/{os.path.basename(png)}", png))
        notes_file = _upload(ctx, "outputs", f"{prefix}/{_safe_ascii(notes_name, 'notes.txt')}", notes_path)
        notes_file["display_name"] = notes_name
        files.append(notes_file)
        files.append(_upload(ctx, "outputs", f"{prefix}/products.json", json_path))

        return {
            "files": files,
            "summary": {
                "project": project,
                "rows": fill_summary["rows"],
                "raster_pages": raster_pages,
                "unconfirmed": fill_summary["unconfirmed"],
                "missing": fill_summary["missing"],
                "completeness_gaps": completeness,
                "cost_usd": round(cost_usd, 4),
                "model": model,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cache_read_input_tokens": cache_read_tok,
                "cache_creation_input_tokens": cache_write_tok,
                "vision_calls": n_vision,
                "local_calls": n_local,
                "bitmap_pages": bitmap_pages,
                "vector_pages": vector_pages,
                "vision_mode": vmode,
                "per_page": per_page,
                "warnings": warnings,
                "products": [
                    {k: p.get(k) for k in ("row_code", "page", "W", "D", "H", "qty", "dim_source", "confirm_dims")}
                    for p in products
                ],
            },
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
