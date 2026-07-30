from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    items = tuple(item.strip().rstrip("/") for item in value.split(",") if item.strip())
    return items or default


class Settings(BaseModel):
    app_name: str
    environment: str
    release_sha: str
    docs_enabled: bool
    allow_demo_identity_headers: bool
    allowed_origins: tuple[str, ...]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("PLATFORM_ENVIRONMENT", "local-sandbox")
    production = environment.strip().lower() == "production"

    return Settings(
        app_name=os.getenv("PLATFORM_API_TITLE", "ORKIO Plataforma 2.0 RC0"),
        environment=environment,
        release_sha=os.getenv("PLATFORM_RELEASE_SHA", "UNPINNED"),
        docs_enabled=_env_bool("PLATFORM_DOCS_ENABLED", not production),
        allow_demo_identity_headers=_env_bool(
            "PLATFORM_DEMO_IDENTITY_HEADERS_ENABLED",
            not production,
        ),
        allowed_origins=_env_csv(
            "PLATFORM_ALLOWED_ORIGINS",
            ("http://localhost:5173",),
        ),
    )
