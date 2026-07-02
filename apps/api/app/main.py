"""FastAPI 入口：CORS + 挂路由。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import glossary, health, jobs

app = FastAPI(title="家具出口内部工具 · API")

_settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(glossary.router, prefix="/api/glossary", tags=["glossary"])
app.include_router(jobs.router, prefix="/api/jobs", tags=["jobs"])
