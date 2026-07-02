"""apps/api 配置：把 shared/py 接入 sys.path + 读取环境变量。"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# 让 apps/api 能 import shared/py 下的包（glossary/claude_client/supabase_client/settings）。
# Docker 镜像里会另外设置 ENV PYTHONPATH=/app/shared/py，这里是本机直跑时的等价兜底，
# 且必须在下面 `from settings import ...` 之前执行。
_SHARED_PY = Path(__file__).resolve().parents[3] / "shared" / "py"
if str(_SHARED_PY) not in sys.path:
    sys.path.insert(0, str(_SHARED_PY))

from settings import Settings as SharedSettings  # noqa: E402


@dataclass(frozen=True)
class ApiSettings:
    shared: SharedSettings
    cors_origins: list[str]


@lru_cache
def get_settings() -> ApiSettings:
    shared = SharedSettings.from_env()
    origins_raw = os.environ.get("API_CORS_ORIGINS", "http://localhost:3000")
    origins = [o.strip() for o in origins_raw.split(",") if o.strip()]
    return ApiSettings(shared=shared, cors_origins=origins)
