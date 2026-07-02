"""术语表只读查表客户端（后端）。

单一真相源 = Supabase `glossary` 表。报价的日→中翻译 与 图纸翻译 **共用同一张表**：
搬 skill 时把内嵌的 EN_DICT/JP_DICT 换成 `load_map("ja","zh")` / `load_map("en","zh")`，
命中查表、未命中送 Claude 翻译。

⚠️ PostgREST 单次最多返回 1000 行；`load_map` 用 range 分页取全，否则词表破千会漏词。
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass

_PAGE = 1000  # PostgREST 单次上限


def _norm(s: str) -> str:
    """NFC 归一化 + 去首尾空白，保证查表键与库里一致。"""
    return unicodedata.normalize("NFC", (s or "").strip())


@dataclass(frozen=True)
class GlossaryHit:
    id: str
    source_term: str
    target_term: str
    domain: str


class GlossaryClient:
    def __init__(self, supabase):
        """supabase: service_role 客户端（见 shared/py/supabase_client）。"""
        self._sb = supabase

    def lookup(
        self, term: str, source_lang: str, target_lang: str, domain: str | None = None
    ) -> GlossaryHit | None:
        """精确命中单个词条（NFC 归一化后比较）。未命中返回 None → 调用方走 LLM。"""
        term = _norm(term)
        q = (
            self._sb.table("glossary")
            .select("id,source_term,target_term,domain")
            .eq("source_lang", source_lang)
            .eq("target_lang", target_lang)
            .eq("source_term", term)
        )
        if domain is not None:
            q = q.eq("domain", domain)
        rows = (q.limit(1).execute().data) or []
        if not rows:
            return None
        r = rows[0]
        return GlossaryHit(
            id=r["id"],
            source_term=r["source_term"],
            target_term=r["target_term"],
            domain=r.get("domain") or "",
        )

    def lookup_batch(
        self, terms: list[str], source_lang: str, target_lang: str
    ) -> dict[str, GlossaryHit]:
        """批量精确查（翻译整页时一次拉，避免 N 次往返）。

        返回 {归一化后的 term: GlossaryHit}；未命中的 key 不出现。同一 term 多 domain 时取先到的一条。
        """
        norm_terms = sorted({_norm(t) for t in terms if _norm(t)})
        hits: dict[str, GlossaryHit] = {}
        chunk_size = 200  # 避免 in.() 查询串过长
        for i in range(0, len(norm_terms), chunk_size):
            chunk = norm_terms[i : i + chunk_size]
            rows = (
                self._sb.table("glossary")
                .select("id,source_term,target_term,domain")
                .eq("source_lang", source_lang)
                .eq("target_lang", target_lang)
                .in_("source_term", chunk)
                .execute()
                .data
            ) or []
            for r in rows:
                st = _norm(r["source_term"])
                if st not in hits:
                    hits[st] = GlossaryHit(
                        id=r["id"],
                        source_term=r["source_term"],
                        target_term=r["target_term"],
                        domain=r.get("domain") or "",
                    )
        return hits

    def load_map(self, source_lang: str, target_lang: str) -> dict[str, str]:
        """一次性拉某语向全表为 {source_term: target_term}（分页取全）。

        等价 skill 里内嵌的 EN_DICT / JP_DICT，供逐 token 命中。
        """
        out: dict[str, str] = {}
        start = 0
        while True:
            batch = (
                self._sb.table("glossary")
                .select("source_term,target_term")
                .eq("source_lang", source_lang)
                .eq("target_lang", target_lang)
                .order("source_term")
                .range(start, start + _PAGE - 1)
                .execute()
                .data
            ) or []
            for r in batch:
                out[_norm(r["source_term"])] = r["target_term"]
            if len(batch) < _PAGE:
                break
            start += _PAGE
        return out
