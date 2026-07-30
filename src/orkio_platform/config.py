from __future__ import annotations

from functools import lru_cache
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "ORKIO Plataforma 2.0 RC0"
    environment: str = "local-sandbox"
    release_sha: str = "UNPINNED"
    docs_enabled: bool = True
    allow_demo_identity_headers: bool = True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
