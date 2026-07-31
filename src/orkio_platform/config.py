from __future__ import annotations

import os
from functools import lru_cache

from pydantic import BaseModel


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {
        "1", "true", "yes", "on",
    }


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value < minimum:
        raise ValueError(f"{name}_BELOW_MINIMUM")
    return value


def _env_csv(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    value = os.getenv(name)
    if not value:
        return default
    items = tuple(
        item.strip().rstrip("/")
        for item in value.split(",")
        if item.strip()
    )
    return items or default


class Settings(BaseModel):
    app_name: str
    environment: str
    release_sha: str
    docs_enabled: bool
    allow_demo_identity_headers: bool
    allowed_origins: tuple[str, ...]
    database_url: str | None
    database_echo: bool
    request_log_enabled: bool
    execution_lease_seconds: int
    execution_stale_after_seconds: int


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv("PLATFORM_ENVIRONMENT", "local-sandbox")
    production = environment.strip().lower() == "production"
    lease_seconds = _env_int(
        "PLATFORM_EXECUTION_LEASE_SECONDS",
        60,
    )
    stale_seconds = _env_int(
        "PLATFORM_EXECUTION_STALE_AFTER_SECONDS",
        300,
    )
    if stale_seconds < lease_seconds:
        raise ValueError(
            "PLATFORM_EXECUTION_STALE_AFTER_SECONDS_BELOW_LEASE"
        )
    return Settings(
        app_name=os.getenv(
            "PLATFORM_API_TITLE",
            "ORKIO Plataforma 2.0 RC1 Premium Hardening",
        ),
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
        database_url=os.getenv("DATABASE_URL") or None,
        database_echo=_env_bool("PLATFORM_DATABASE_ECHO", False),
        request_log_enabled=_env_bool(
            "PLATFORM_REQUEST_LOG_ENABLED",
            True,
        ),
        execution_lease_seconds=lease_seconds,
        execution_stale_after_seconds=stale_seconds,
    )
