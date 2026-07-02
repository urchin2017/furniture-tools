"""术语表只读查表端点。

前端 CRUD 仍直连 Supabase（anon+RLS，见 apps/web `(app)/glossary`）；这里给后端其它
模块（报价生成、图纸翻译判断步骤）内部复用同一张 `glossary` 表提供 HTTP 出口，
也顺带验证 shared/py 到 apps/api 的接线是通的。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from supabase import Client

from app.deps import get_current_user, get_supabase

from glossary import GlossaryClient

router = APIRouter(dependencies=[Depends(get_current_user)])


class LookupBatchRequest(BaseModel):
    terms: list[str]
    source_lang: str
    target_lang: str


class LookupHit(BaseModel):
    target_term: str
    domain: str


@router.post("/lookup-batch")
def lookup_batch(
    body: LookupBatchRequest, supabase: Client = Depends(get_supabase)
) -> dict[str, LookupHit]:
    hits = GlossaryClient(supabase).lookup_batch(body.terms, body.source_lang, body.target_lang)
    return {
        term: LookupHit(target_term=hit.target_term, domain=hit.domain)
        for term, hit in hits.items()
    }
