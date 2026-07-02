"""共享配置：从环境变量读取（可选加载 .env）。无第三方依赖，方便单测。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | os.PathLike | None = None) -> None:
    """把简单的 KEY=VALUE .env 读进 os.environ（仅当 key 尚未设置）。

    找不到路径时，从本文件向上层目录寻找 furniture-tools/.env。
    """
    if path is None:
        here = Path(__file__).resolve()
        for parent in here.parents:
            cand = parent / ".env"
            if cand.exists():
                path = cand
                break
        else:
            return
    p = Path(path)
    if not p.exists():
        return
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


@dataclass(frozen=True)
class Settings:
    supabase_url: str
    supabase_service_role_key: str
    anthropic_api_key: str
    claude_model: str = "claude-opus-4-8"

    @classmethod
    def from_env(cls, *, load_dotenv: bool = True) -> "Settings":
        if load_dotenv:
            load_env()

        def req(name: str) -> str:
            v = os.environ.get(name, "")
            if not v:
                raise RuntimeError(f"缺少环境变量 {name}（检查 furniture-tools/.env）")
            return v

        return cls(
            supabase_url=req("NEXT_PUBLIC_SUPABASE_URL"),
            supabase_service_role_key=req("SUPABASE_SERVICE_ROLE_KEY"),
            anthropic_api_key=req("ANTHROPIC_API_KEY"),
            claude_model=os.environ.get("CLAUDE_MODEL", "claude-opus-4-8"),
        )
