from __future__ import annotations

import os
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, SecretStr

from orkio_platform.version import RELEASE_VERSION


AuthMode = Literal[
    "demo_headers",
    "oidc_introspection",
    "external_required",
]

LLMProviderMode = Literal[
    "deterministic",
    "openai_responses",
]


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _env_int(
    name: str,
    default: int,
    *,
    minimum: int = 0,
    maximum: int | None = None,
) -> int:
    raw = os.getenv(name)
    value = default if raw is None else int(raw)
    if value < minimum:
        raise ValueError(f"{name}_BELOW_MINIMUM")
    if maximum is not None and value > maximum:
        raise ValueError(f"{name}_ABOVE_MAXIMUM")
    return value


def _env_csv(
    name: str,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    value = os.getenv(name)
    if value is None:
        return default
    items = tuple(
        item.strip()
        for item in value.split(",")
        if item.strip()
    )
    return items


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _resolve_auth_mode(*, production: bool) -> AuthMode:
    requested = _optional_env("PLATFORM_AUTH_MODE")
    if requested is None:
        legacy_demo = _env_bool(
            "PLATFORM_DEMO_IDENTITY_HEADERS_ENABLED",
            not production,
        )
        mode: AuthMode = (
            "demo_headers"
            if legacy_demo
            else "external_required"
        )
    else:
        normalized = requested.lower()
        allowed = {
            "demo_headers",
            "oidc_introspection",
            "external_required",
        }
        if normalized not in allowed:
            raise ValueError("PLATFORM_AUTH_MODE_INVALID")
        mode = normalized  # type: ignore[assignment]

    if production and mode == "demo_headers":
        raise ValueError(
            "DEMO_IDENTITY_HEADERS_FORBIDDEN_IN_PRODUCTION"
        )
    return mode


def _require_https(
    name: str,
    value: str | None,
    *,
    production: bool,
) -> None:
    if production and value and not value.startswith("https://"):
        raise ValueError(f"{name}_HTTPS_REQUIRED")


class Settings(BaseModel):
    app_name: str
    environment: str
    release_sha: str
    docs_enabled: bool

    auth_mode: AuthMode
    allow_demo_identity_headers: bool
    demo_allowed_tenants: tuple[str, ...]
    demo_allowed_users: tuple[str, ...]
    demo_admin_enabled: bool
    demo_admin_users: tuple[str, ...]

    oidc_issuer: str | None
    oidc_audience: str | None
    oidc_authorization_endpoint: str | None
    oidc_token_endpoint: str | None
    oidc_introspection_endpoint: str | None
    oidc_public_client_id: str | None
    oidc_introspection_client_id: str | None
    oidc_introspection_client_secret: str | None
    oidc_redirect_uri: str | None
    oidc_scopes: tuple[str, ...]
    oidc_user_claim: str
    oidc_tenant_claim: str
    oidc_roles_claim: str
    oidc_admin_roles: tuple[str, ...]
    oidc_member_roles: tuple[str, ...]
    oidc_clock_skew_seconds: int
    oidc_http_timeout_seconds: int
    oidc_cache_seconds: int

    allowed_origins: tuple[str, ...]
    database_url: str | None
    database_echo: bool
    request_log_enabled: bool
    execution_lease_seconds: int
    execution_stale_after_seconds: int

    llm_provider: LLMProviderMode
    llm_history_messages: int
    llm_max_context_chars: int
    openai_api_key: SecretStr | None
    openai_default_model: str | None
    openai_base_url: str
    openai_organization_id: str | None
    openai_project_id: str | None
    openai_timeout_seconds: int
    openai_max_retries: int
    openai_max_output_tokens: int
    openai_store_responses: bool

    realtime_streaming_enabled: bool
    multiagent_enabled: bool
    multiagent_max_contributors: int
    multiagent_team_agents: tuple[str, ...]
    assisted_evolution_enabled: bool

    @property
    def oidc_configured(self) -> bool:
        required = (
            self.oidc_issuer,
            self.oidc_audience,
            self.oidc_authorization_endpoint,
            self.oidc_token_endpoint,
            self.oidc_introspection_endpoint,
            self.oidc_public_client_id,
            self.oidc_introspection_client_id,
            self.oidc_introspection_client_secret,
            self.oidc_redirect_uri,
        )
        return all(required)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    environment = os.getenv(
        "PLATFORM_ENVIRONMENT",
        "local-sandbox",
    ).strip()
    production = environment.lower() == "production"
    auth_mode = _resolve_auth_mode(production=production)

    default_tenant = os.getenv(
        "PLATFORM_DEMO_TENANT_ID",
        "tenant-demo",
    ).strip()
    default_user = os.getenv(
        "PLATFORM_DEMO_USER_ID",
        "user-demo",
    ).strip()
    if not default_tenant or not default_user:
        raise ValueError("DEMO_IDENTITY_DEFAULT_INVALID")

    demo_allowed_tenants = _env_csv(
        "PLATFORM_DEMO_ALLOWED_TENANTS",
        (default_tenant,),
    )
    demo_allowed_users = _env_csv(
        "PLATFORM_DEMO_ALLOWED_USERS",
        (default_user,),
    )
    demo_admin_enabled = _env_bool(
        "PLATFORM_DEMO_ADMIN_ENABLED",
        False,
    )
    demo_admin_users = _env_csv(
        "PLATFORM_DEMO_ADMIN_USERS",
        (),
    )
    if demo_admin_enabled and not demo_admin_users:
        raise ValueError("DEMO_ADMIN_USERS_REQUIRED")
    if not set(demo_admin_users).issubset(
        set(demo_allowed_users)
    ):
        raise ValueError(
            "DEMO_ADMIN_USERS_MUST_BE_ALLOWED_USERS"
        )

    lease_seconds = _env_int(
        "PLATFORM_EXECUTION_LEASE_SECONDS",
        60,
        minimum=1,
    )
    stale_seconds = _env_int(
        "PLATFORM_EXECUTION_STALE_AFTER_SECONDS",
        300,
        minimum=1,
    )
    if stale_seconds < lease_seconds:
        raise ValueError(
            "PLATFORM_EXECUTION_STALE_AFTER_SECONDS_BELOW_LEASE"
        )

    issuer = _optional_env("PLATFORM_OIDC_ISSUER")
    if issuer:
        issuer = issuer.rstrip("/")
    oidc_authorization_endpoint = _optional_env(
        "PLATFORM_OIDC_AUTHORIZATION_ENDPOINT"
    )
    oidc_token_endpoint = _optional_env(
        "PLATFORM_OIDC_TOKEN_ENDPOINT"
    )
    oidc_introspection_endpoint = _optional_env(
        "PLATFORM_OIDC_INTROSPECTION_ENDPOINT"
    )
    oidc_redirect_uri = _optional_env(
        "PLATFORM_OIDC_REDIRECT_URI"
    )

    for name, value in (
        ("PLATFORM_OIDC_ISSUER", issuer),
        (
            "PLATFORM_OIDC_AUTHORIZATION_ENDPOINT",
            oidc_authorization_endpoint,
        ),
        (
            "PLATFORM_OIDC_TOKEN_ENDPOINT",
            oidc_token_endpoint,
        ),
        (
            "PLATFORM_OIDC_INTROSPECTION_ENDPOINT",
            oidc_introspection_endpoint,
        ),
        (
            "PLATFORM_OIDC_REDIRECT_URI",
            oidc_redirect_uri,
        ),
    ):
        _require_https(
            name,
            value,
            production=production,
        )

    allowed_origins = _env_csv(
        "PLATFORM_ALLOWED_ORIGINS",
        ("http://localhost:5173",),
    )
    if production and "*" in allowed_origins:
        raise ValueError(
            "PLATFORM_ALLOWED_ORIGINS_WILDCARD_FORBIDDEN"
        )

    requested_llm_provider = os.getenv(
        "PLATFORM_LLM_PROVIDER",
        "deterministic",
    ).strip().lower()
    allowed_llm_providers = {
        "deterministic",
        "openai_responses",
    }
    if requested_llm_provider not in allowed_llm_providers:
        raise ValueError("PLATFORM_LLM_PROVIDER_INVALID")
    llm_provider: LLMProviderMode = requested_llm_provider  # type: ignore[assignment]

    openai_api_key = _optional_env("OPENAI_API_KEY")
    openai_default_model = _optional_env(
        "OPENAI_DEFAULT_MODEL"
    )
    openai_base_url = os.getenv(
        "OPENAI_BASE_URL",
        "https://api.openai.com/v1",
    ).strip().rstrip("/")
    if not openai_base_url:
        raise ValueError("OPENAI_BASE_URL_INVALID")
    _require_https(
        "OPENAI_BASE_URL",
        openai_base_url,
        production=production,
    )

    if llm_provider == "openai_responses":
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY_REQUIRED")
        if openai_default_model is None:
            raise ValueError("OPENAI_DEFAULT_MODEL_REQUIRED")

    settings = Settings(
        app_name=os.getenv(
            "PLATFORM_API_TITLE",
            f"ORKIO Plataforma 2.0 Premium Auth R{RELEASE_VERSION}",
        ),
        environment=environment,
        release_sha=os.getenv(
            "PLATFORM_RELEASE_SHA",
            "UNPINNED",
        ),
        docs_enabled=_env_bool(
            "PLATFORM_DOCS_ENABLED",
            not production,
        ),
        auth_mode=auth_mode,
        allow_demo_identity_headers=(
            auth_mode == "demo_headers"
        ),
        demo_allowed_tenants=demo_allowed_tenants,
        demo_allowed_users=demo_allowed_users,
        demo_admin_enabled=demo_admin_enabled,
        demo_admin_users=demo_admin_users,
        oidc_issuer=issuer,
        oidc_audience=_optional_env(
            "PLATFORM_OIDC_AUDIENCE"
        ),
        oidc_authorization_endpoint=(
            oidc_authorization_endpoint
        ),
        oidc_token_endpoint=oidc_token_endpoint,
        oidc_introspection_endpoint=(
            oidc_introspection_endpoint
        ),
        oidc_public_client_id=_optional_env(
            "PLATFORM_OIDC_PUBLIC_CLIENT_ID"
        ),
        oidc_introspection_client_id=_optional_env(
            "PLATFORM_OIDC_INTROSPECTION_CLIENT_ID"
        ),
        oidc_introspection_client_secret=_optional_env(
            "PLATFORM_OIDC_INTROSPECTION_CLIENT_SECRET"
        ),
        oidc_redirect_uri=oidc_redirect_uri,
        oidc_scopes=_env_csv(
            "PLATFORM_OIDC_SCOPES",
            ("openid", "profile", "email"),
        ),
        oidc_user_claim=os.getenv(
            "PLATFORM_OIDC_USER_CLAIM",
            "sub",
        ).strip(),
        oidc_tenant_claim=os.getenv(
            "PLATFORM_OIDC_TENANT_CLAIM",
            "tenant_id",
        ).strip(),
        oidc_roles_claim=os.getenv(
            "PLATFORM_OIDC_ROLES_CLAIM",
            "roles",
        ).strip(),
        oidc_admin_roles=_env_csv(
            "PLATFORM_OIDC_ADMIN_ROLES",
            ("orkio_admin",),
        ),
        oidc_member_roles=_env_csv(
            "PLATFORM_OIDC_MEMBER_ROLES",
            ("orkio_member",),
        ),
        oidc_clock_skew_seconds=_env_int(
            "PLATFORM_OIDC_CLOCK_SKEW_SECONDS",
            30,
            minimum=0,
            maximum=300,
        ),
        oidc_http_timeout_seconds=_env_int(
            "PLATFORM_OIDC_HTTP_TIMEOUT_SECONDS",
            5,
            minimum=1,
            maximum=30,
        ),
        oidc_cache_seconds=_env_int(
            "PLATFORM_OIDC_CACHE_SECONDS",
            15,
            minimum=0,
            maximum=60,
        ),
        allowed_origins=allowed_origins,
        database_url=os.getenv("DATABASE_URL") or None,
        database_echo=_env_bool(
            "PLATFORM_DATABASE_ECHO",
            False,
        ),
        request_log_enabled=_env_bool(
            "PLATFORM_REQUEST_LOG_ENABLED",
            True,
        ),
        execution_lease_seconds=lease_seconds,
        execution_stale_after_seconds=stale_seconds,
        llm_provider=llm_provider,
        llm_history_messages=_env_int(
            "PLATFORM_LLM_HISTORY_MESSAGES",
            20,
            minimum=0,
            maximum=100,
        ),
        llm_max_context_chars=_env_int(
            "PLATFORM_LLM_MAX_CONTEXT_CHARS",
            100_000,
            minimum=1_000,
            maximum=1_000_000,
        ),
        openai_api_key=openai_api_key,
        openai_default_model=openai_default_model,
        openai_base_url=openai_base_url,
        openai_organization_id=_optional_env(
            "OPENAI_ORGANIZATION_ID"
        ),
        openai_project_id=_optional_env(
            "OPENAI_PROJECT_ID"
        ),
        openai_timeout_seconds=_env_int(
            "OPENAI_TIMEOUT_SECONDS",
            120,
            minimum=1,
            maximum=600,
        ),
        openai_max_retries=_env_int(
            "OPENAI_MAX_RETRIES",
            2,
            minimum=0,
            maximum=5,
        ),
        openai_max_output_tokens=_env_int(
            "OPENAI_MAX_OUTPUT_TOKENS",
            4096,
            minimum=1,
            maximum=100_000,
        ),
        openai_store_responses=_env_bool(
            "OPENAI_STORE_RESPONSES",
            False,
        ),
        realtime_streaming_enabled=_env_bool(
            "PLATFORM_REALTIME_STREAMING_ENABLED",
            False,
        ),
        multiagent_enabled=_env_bool(
            "PLATFORM_MULTIAGENT_ENABLED",
            False,
        ),
        multiagent_max_contributors=_env_int(
            "PLATFORM_MULTIAGENT_MAX_CONTRIBUTORS",
            2,
            minimum=0,
            maximum=3,
        ),
        multiagent_team_agents=_env_csv(
            "PLATFORM_MULTIAGENT_TEAM_AGENTS",
            ("Orion", "Chris", "Laura"),
        ),
        assisted_evolution_enabled=_env_bool(
            "PLATFORM_ASSISTED_EVOLUTION_ENABLED",
            False,
        ),
    )

    if (
        settings.auth_mode == "oidc_introspection"
        and not settings.oidc_configured
    ):
        raise ValueError("OIDC_CONFIGURATION_INCOMPLETE")
    if not settings.oidc_user_claim:
        raise ValueError("PLATFORM_OIDC_USER_CLAIM_INVALID")
    if not settings.oidc_tenant_claim:
        raise ValueError("PLATFORM_OIDC_TENANT_CLAIM_INVALID")
    if not settings.oidc_roles_claim:
        raise ValueError("PLATFORM_OIDC_ROLES_CLAIM_INVALID")
    if not settings.oidc_member_roles:
        raise ValueError("PLATFORM_OIDC_MEMBER_ROLES_REQUIRED")
    allowed_team_agents = {"Orion", "Chris", "Laura"}
    if any(
        agent_id not in allowed_team_agents
        for agent_id in settings.multiagent_team_agents
    ):
        raise ValueError("PLATFORM_MULTIAGENT_TEAM_AGENTS_INVALID")
    return settings
