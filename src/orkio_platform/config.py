from __future__ import annotations

import base64
import os
import re
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

VoiceProviderMode = Literal[
    "disabled",
    "openai_realtime",
]


GitHubAuthMode = Literal[
    "disabled",
    "token",
    "github_app",
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

    realtime_voice_enabled: bool
    voice_actions_enabled: bool
    multiagent_voice_enabled: bool
    voice_provider: VoiceProviderMode
    openai_realtime_model: str
    openai_realtime_voice: str
    openai_realtime_transcription_model: str
    voice_max_session_seconds: int
    voice_idle_timeout_seconds: int
    voice_max_reconnect_attempts: int
    voice_reconnect_deadline_seconds: int
    voice_resume_token_ttl_seconds: int
    voice_resume_token_secret: SecretStr | None
    voice_max_active_sessions_per_user: int
    voice_raw_audio_retention: Literal["none", "tenant_policy"]
    voice_transcript_retention: Literal["thread_policy"]
    voice_provider_retention_confirmed: bool
    voice_consent_required: bool
    voice_audit_content: Literal["metadata_only"]
    voice_log_transcript_content: bool

    github_integration_enabled: bool
    github_read_only: bool
    github_auth_mode: GitHubAuthMode
    github_token: SecretStr | None
    github_app_id: str | None
    github_app_installation_id: int | None
    github_app_private_key_b64: SecretStr | None
    github_api_base_url: str
    github_api_version: str
    github_allowed_repositories: tuple[str, ...]
    github_default_ref: str
    github_http_timeout_seconds: int
    github_audit_deadline_seconds: int
    github_max_response_bytes: int
    github_max_tree_entries: int
    github_max_files_per_audit: int
    github_max_file_bytes: int
    github_max_total_chars: int
    github_allow_content_read: bool
    github_allow_metadata_read: bool
    github_allow_diff_read: bool
    github_allowed_roles: tuple[str, ...]
    github_allowed_tenants: tuple[str, ...]
    github_allowed_users: tuple[str, ...]
    github_orion_auto_audit_enabled: bool
    github_allow_write: bool
    github_allow_branch_create: bool
    github_allow_commit: bool
    github_allow_pull_request: bool
    github_allow_merge: bool
    github_allow_workflow_dispatch: bool

    multiagent_enabled: bool
    multiagent_max_contributors: int
    multiagent_team_agents: tuple[str, ...]
    multiagent_contribution_max_chars: int
    multiagent_contribution_max_output_tokens: int
    multiagent_owner_max_output_tokens: int
    multiagent_contribution_latency_budget_ms: int
    multiagent_turn_latency_budget_ms: int
    multiagent_history_messages: int
    multiagent_max_context_chars: int
    multiagent_turn_max_total_tokens: int
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

    @property
    def github_configured(self) -> bool:
        if not self.github_integration_enabled:
            return False
        if not self.github_allowed_repositories:
            return False
        if self.github_auth_mode == "token":
            return self.github_token is not None
        if self.github_auth_mode == "github_app":
            return all(
                (
                    self.github_app_id,
                    self.github_app_installation_id,
                    self.github_app_private_key_b64,
                )
            )
        return False


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

    requested_voice_provider = os.getenv(
        "PLATFORM_VOICE_PROVIDER",
        "disabled",
    ).strip().lower()
    allowed_voice_providers = {
        "disabled",
        "openai_realtime",
    }
    if requested_voice_provider not in allowed_voice_providers:
        raise ValueError("PLATFORM_VOICE_PROVIDER_INVALID")
    voice_provider: VoiceProviderMode = requested_voice_provider  # type: ignore[assignment]

    realtime_voice_enabled = _env_bool(
        "PLATFORM_REALTIME_VOICE_ENABLED",
        False,
    )
    voice_provider_retention_confirmed = _env_bool(
        "PLATFORM_VOICE_PROVIDER_RETENTION_CONFIRMED",
        False,
    )
    raw_voice_resume_token_secret = _optional_env(
        "PLATFORM_VOICE_RESUME_TOKEN_SECRET"
    )
    voice_resume_token_secret = (
        None
        if raw_voice_resume_token_secret is None
        else SecretStr(raw_voice_resume_token_secret)
    )
    voice_raw_audio_retention = os.getenv(
        "PLATFORM_VOICE_RAW_AUDIO_RETENTION",
        "none",
    ).strip().lower()
    if voice_raw_audio_retention not in {"none", "tenant_policy"}:
        raise ValueError("PLATFORM_VOICE_RAW_AUDIO_RETENTION_INVALID")
    voice_transcript_retention = os.getenv(
        "PLATFORM_VOICE_TRANSCRIPT_RETENTION",
        "thread_policy",
    ).strip().lower()
    if voice_transcript_retention != "thread_policy":
        raise ValueError("PLATFORM_VOICE_TRANSCRIPT_RETENTION_INVALID")
    voice_audit_content = os.getenv(
        "PLATFORM_VOICE_AUDIT_CONTENT",
        "metadata_only",
    ).strip().lower()
    if voice_audit_content != "metadata_only":
        raise ValueError("PLATFORM_VOICE_AUDIT_CONTENT_INVALID")

    if realtime_voice_enabled:
        if voice_provider != "openai_realtime":
            raise ValueError("PLATFORM_VOICE_PROVIDER_REQUIRED")
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY_REQUIRED_FOR_VOICE")
        if not voice_provider_retention_confirmed:
            raise ValueError(
                "VOICE_PROVIDER_RETENTION_CONFIRMATION_REQUIRED"
            )
        if voice_resume_token_secret is None:
            raise ValueError("PLATFORM_VOICE_RESUME_TOKEN_SECRET_REQUIRED")
        if len(voice_resume_token_secret.get_secret_value()) < 32:
            raise ValueError("PLATFORM_VOICE_RESUME_TOKEN_SECRET_TOO_SHORT")

    github_integration_enabled = _env_bool(
        "PLATFORM_GITHUB_INTEGRATION_ENABLED",
        False,
    )
    github_read_only = _env_bool(
        "PLATFORM_GITHUB_READ_ONLY",
        True,
    )
    requested_github_auth_mode = os.getenv(
        "PLATFORM_GITHUB_AUTH_MODE",
        "disabled",
    ).strip().lower()
    allowed_github_auth_modes = {
        "disabled",
        "token",
        "github_app",
    }
    if requested_github_auth_mode not in allowed_github_auth_modes:
        raise ValueError("PLATFORM_GITHUB_AUTH_MODE_INVALID")
    github_auth_mode: GitHubAuthMode = requested_github_auth_mode  # type: ignore[assignment]

    github_api_base_url = os.getenv(
        "PLATFORM_GITHUB_API_BASE_URL",
        "https://api.github.com",
    ).strip().rstrip("/")
    if not github_api_base_url:
        raise ValueError("PLATFORM_GITHUB_API_BASE_URL_INVALID")
    _require_https(
        "PLATFORM_GITHUB_API_BASE_URL",
        github_api_base_url,
        production=production,
    )
    if github_api_base_url != "https://api.github.com":
        raise ValueError(
            "PLATFORM_GITHUB_API_BASE_URL_UNSUPPORTED"
        )
    github_api_version = os.getenv(
        "PLATFORM_GITHUB_API_VERSION",
        "2026-03-10",
    ).strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", github_api_version):
        raise ValueError("PLATFORM_GITHUB_API_VERSION_INVALID")

    github_allowed_repositories = _env_csv(
        "PLATFORM_GITHUB_ALLOWED_REPOSITORIES",
        (),
    )
    repository_pattern = re.compile(
        r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
    )
    if any(
        not repository_pattern.fullmatch(repository)
        for repository in github_allowed_repositories
    ):
        raise ValueError(
            "PLATFORM_GITHUB_ALLOWED_REPOSITORIES_INVALID"
        )
    if len(github_allowed_repositories) > 100:
        raise ValueError(
            "PLATFORM_GITHUB_ALLOWED_REPOSITORIES_LIMIT_EXCEEDED"
        )
    normalized_repositories = {
        repository.casefold()
        for repository in github_allowed_repositories
    }
    if len(normalized_repositories) != len(
        github_allowed_repositories
    ):
        raise ValueError(
            "PLATFORM_GITHUB_ALLOWED_REPOSITORIES_DUPLICATED"
        )

    github_default_ref = os.getenv(
        "PLATFORM_GITHUB_DEFAULT_REF",
        "main",
    ).strip()
    if (
        not github_default_ref
        or ".." in github_default_ref
        or any(character.isspace() for character in github_default_ref)
    ):
        raise ValueError("PLATFORM_GITHUB_DEFAULT_REF_INVALID")

    github_token_value = _optional_env("PLATFORM_GITHUB_TOKEN")
    github_token = (
        SecretStr(github_token_value)
        if github_token_value is not None
        else None
    )
    github_app_private_key_value = _optional_env(
        "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64"
    )
    github_app_private_key_b64 = (
        SecretStr(github_app_private_key_value)
        if github_app_private_key_value is not None
        else None
    )
    raw_installation_id = _optional_env(
        "PLATFORM_GITHUB_APP_INSTALLATION_ID"
    )
    try:
        github_app_installation_id = (
            None
            if raw_installation_id is None
            else int(raw_installation_id)
        )
    except ValueError as exc:
        raise ValueError(
            "PLATFORM_GITHUB_APP_INSTALLATION_ID_INVALID"
        ) from exc
    if (
        github_app_installation_id is not None
        and github_app_installation_id <= 0
    ):
        raise ValueError(
            "PLATFORM_GITHUB_APP_INSTALLATION_ID_INVALID"
        )

    github_allowed_roles = _env_csv(
        "PLATFORM_GITHUB_ALLOWED_ROLES",
        ("admin",),
    )
    valid_github_roles = {"member", "admin", "auditor"}
    if (
        not github_allowed_roles
        or any(
            role not in valid_github_roles
            for role in github_allowed_roles
        )
    ):
        raise ValueError("PLATFORM_GITHUB_ALLOWED_ROLES_INVALID")

    github_allow_write = _env_bool(
        "PLATFORM_GITHUB_ALLOW_WRITE",
        False,
    )
    github_allow_branch_create = _env_bool(
        "PLATFORM_GITHUB_ALLOW_BRANCH_CREATE",
        False,
    )
    github_allow_commit = _env_bool(
        "PLATFORM_GITHUB_ALLOW_COMMIT",
        False,
    )
    github_allow_pull_request = _env_bool(
        "PLATFORM_GITHUB_ALLOW_PULL_REQUEST",
        False,
    )
    github_allow_merge = _env_bool(
        "PLATFORM_GITHUB_ALLOW_MERGE",
        False,
    )
    github_allow_workflow_dispatch = _env_bool(
        "PLATFORM_GITHUB_ALLOW_WORKFLOW_DISPATCH",
        False,
    )
    if any(
        (
            github_allow_write,
            github_allow_branch_create,
            github_allow_commit,
            github_allow_pull_request,
            github_allow_merge,
            github_allow_workflow_dispatch,
        )
    ):
        raise ValueError("PLATFORM_GITHUB_READONLY_VIOLATION")
    if not github_read_only:
        raise ValueError("PLATFORM_GITHUB_READ_ONLY_REQUIRED")

    if github_integration_enabled:
        if github_auth_mode == "disabled":
            raise ValueError("PLATFORM_GITHUB_AUTH_MODE_REQUIRED")
        if not github_allowed_repositories:
            raise ValueError(
                "PLATFORM_GITHUB_ALLOWED_REPOSITORIES_REQUIRED"
            )
        if github_auth_mode == "token" and github_token is None:
            raise ValueError("PLATFORM_GITHUB_TOKEN_REQUIRED")
        if github_auth_mode == "github_app":
            github_app_id = _optional_env(
                "PLATFORM_GITHUB_APP_ID"
            )
            if (
                github_app_id is None
                or github_app_installation_id is None
                or github_app_private_key_b64 is None
            ):
                raise ValueError(
                    "PLATFORM_GITHUB_APP_CONFIGURATION_INCOMPLETE"
                )
            try:
                decoded_private_key = base64.b64decode(
                    github_app_private_key_b64.get_secret_value(),
                    validate=True,
                )
            except Exception as exc:
                raise ValueError(
                    "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64_INVALID"
                ) from exc
            if b"PRIVATE KEY" not in decoded_private_key:
                raise ValueError(
                    "PLATFORM_GITHUB_APP_PRIVATE_KEY_B64_INVALID"
                )

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
        realtime_voice_enabled=realtime_voice_enabled,
        voice_actions_enabled=_env_bool(
            "PLATFORM_VOICE_ACTIONS_ENABLED",
            False,
        ),
        multiagent_voice_enabled=_env_bool(
            "PLATFORM_MULTIAGENT_VOICE_ENABLED",
            False,
        ),
        voice_provider=voice_provider,
        openai_realtime_model=os.getenv(
            "OPENAI_REALTIME_MODEL",
            "gpt-realtime",
        ).strip(),
        openai_realtime_voice=os.getenv(
            "OPENAI_REALTIME_VOICE",
            "marin",
        ).strip(),
        openai_realtime_transcription_model=os.getenv(
            "OPENAI_REALTIME_TRANSCRIPTION_MODEL",
            "gpt-4o-mini-transcribe",
        ).strip(),
        voice_max_session_seconds=_env_int(
            "PLATFORM_VOICE_MAX_SESSION_SECONDS",
            1800,
            minimum=60,
            maximum=14_400,
        ),
        voice_idle_timeout_seconds=_env_int(
            "PLATFORM_VOICE_IDLE_TIMEOUT_SECONDS",
            120,
            minimum=15,
            maximum=3600,
        ),
        voice_max_reconnect_attempts=_env_int(
            "PLATFORM_VOICE_MAX_RECONNECT_ATTEMPTS",
            3,
            minimum=0,
            maximum=20,
        ),
        voice_reconnect_deadline_seconds=_env_int(
            "PLATFORM_VOICE_RECONNECT_DEADLINE_SECONDS",
            30,
            minimum=1,
            maximum=300,
        ),
        voice_resume_token_ttl_seconds=_env_int(
            "PLATFORM_VOICE_RESUME_TOKEN_TTL_SECONDS",
            120,
            minimum=15,
            maximum=3600,
        ),
        voice_resume_token_secret=voice_resume_token_secret,
        voice_max_active_sessions_per_user=_env_int(
            "PLATFORM_VOICE_MAX_ACTIVE_SESSIONS_PER_USER",
            1,
            minimum=1,
            maximum=5,
        ),
        voice_raw_audio_retention=voice_raw_audio_retention,  # type: ignore[arg-type]
        voice_transcript_retention=voice_transcript_retention,  # type: ignore[arg-type]
        voice_provider_retention_confirmed=(
            voice_provider_retention_confirmed
        ),
        voice_consent_required=_env_bool(
            "PLATFORM_VOICE_CONSENT_REQUIRED",
            True,
        ),
        voice_audit_content=voice_audit_content,  # type: ignore[arg-type]
        voice_log_transcript_content=_env_bool(
            "PLATFORM_VOICE_LOG_TRANSCRIPT_CONTENT",
            False,
        ),
        github_integration_enabled=github_integration_enabled,
        github_read_only=github_read_only,
        github_auth_mode=github_auth_mode,
        github_token=github_token,
        github_app_id=_optional_env("PLATFORM_GITHUB_APP_ID"),
        github_app_installation_id=github_app_installation_id,
        github_app_private_key_b64=github_app_private_key_b64,
        github_api_base_url=github_api_base_url,
        github_api_version=github_api_version,
        github_allowed_repositories=github_allowed_repositories,
        github_default_ref=github_default_ref,
        github_http_timeout_seconds=_env_int(
            "PLATFORM_GITHUB_HTTP_TIMEOUT_SECONDS",
            20,
            minimum=1,
            maximum=120,
        ),
        github_audit_deadline_seconds=_env_int(
            "PLATFORM_GITHUB_AUDIT_DEADLINE_SECONDS",
            60,
            minimum=5,
            maximum=300,
        ),
        github_max_response_bytes=_env_int(
            "PLATFORM_GITHUB_MAX_RESPONSE_BYTES",
            8_000_000,
            minimum=100_000,
            maximum=10_000_000,
        ),
        github_max_tree_entries=_env_int(
            "PLATFORM_GITHUB_MAX_TREE_ENTRIES",
            5_000,
            minimum=1,
            maximum=100_000,
        ),
        github_max_files_per_audit=_env_int(
            "PLATFORM_GITHUB_MAX_FILES_PER_AUDIT",
            24,
            minimum=1,
            maximum=200,
        ),
        github_max_file_bytes=_env_int(
            "PLATFORM_GITHUB_MAX_FILE_BYTES",
            250_000,
            minimum=1_000,
            maximum=5_000_000,
        ),
        github_max_total_chars=_env_int(
            "PLATFORM_GITHUB_MAX_TOTAL_CHARS",
            80_000,
            minimum=5_000,
            maximum=500_000,
        ),
        github_allow_content_read=_env_bool(
            "PLATFORM_GITHUB_ALLOW_CONTENT_READ",
            True,
        ),
        github_allow_metadata_read=_env_bool(
            "PLATFORM_GITHUB_ALLOW_METADATA_READ",
            True,
        ),
        github_allow_diff_read=_env_bool(
            "PLATFORM_GITHUB_ALLOW_DIFF_READ",
            True,
        ),
        github_allowed_roles=github_allowed_roles,
        github_allowed_tenants=_env_csv(
            "PLATFORM_GITHUB_ALLOWED_TENANTS",
            (),
        ),
        github_allowed_users=_env_csv(
            "PLATFORM_GITHUB_ALLOWED_USERS",
            (),
        ),
        github_orion_auto_audit_enabled=_env_bool(
            "PLATFORM_GITHUB_ORION_AUTO_AUDIT_ENABLED",
            False,
        ),
        github_allow_write=github_allow_write,
        github_allow_branch_create=github_allow_branch_create,
        github_allow_commit=github_allow_commit,
        github_allow_pull_request=github_allow_pull_request,
        github_allow_merge=github_allow_merge,
        github_allow_workflow_dispatch=(
            github_allow_workflow_dispatch
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
        multiagent_contribution_max_chars=_env_int(
            "PLATFORM_MULTIAGENT_CONTRIBUTION_MAX_CHARS",
            4_000,
            minimum=500,
            maximum=20_000,
        ),
        multiagent_contribution_max_output_tokens=_env_int(
            "PLATFORM_MULTIAGENT_CONTRIBUTION_MAX_OUTPUT_TOKENS",
            900,
            minimum=64,
            maximum=8_192,
        ),
        multiagent_owner_max_output_tokens=_env_int(
            "PLATFORM_MULTIAGENT_OWNER_MAX_OUTPUT_TOKENS",
            1_200,
            minimum=64,
            maximum=8_192,
        ),
        multiagent_contribution_latency_budget_ms=_env_int(
            "PLATFORM_MULTIAGENT_CONTRIBUTION_LATENCY_BUDGET_MS",
            15_000,
            minimum=100,
            maximum=300_000,
        ),
        multiagent_turn_latency_budget_ms=_env_int(
            "PLATFORM_MULTIAGENT_TURN_LATENCY_BUDGET_MS",
            25_000,
            minimum=100,
            maximum=600_000,
        ),
        multiagent_history_messages=_env_int(
            "PLATFORM_MULTIAGENT_HISTORY_MESSAGES",
            4,
            minimum=0,
            maximum=20,
        ),
        multiagent_max_context_chars=_env_int(
            "PLATFORM_MULTIAGENT_MAX_CONTEXT_CHARS",
            20_000,
            minimum=1_000,
            maximum=200_000,
        ),
        multiagent_turn_max_total_tokens=_env_int(
            "PLATFORM_MULTIAGENT_TURN_MAX_TOTAL_TOKENS",
            7_000,
            minimum=256,
            maximum=100_000,
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
    if settings.realtime_voice_enabled:
        if not settings.openai_realtime_model:
            raise ValueError("OPENAI_REALTIME_MODEL_REQUIRED")
        if not settings.openai_realtime_voice:
            raise ValueError("OPENAI_REALTIME_VOICE_REQUIRED")
        if not settings.openai_realtime_transcription_model:
            raise ValueError(
                "OPENAI_REALTIME_TRANSCRIPTION_MODEL_REQUIRED"
            )
    if settings.voice_actions_enabled and not settings.realtime_voice_enabled:
        raise ValueError("VOICE_ACTIONS_REQUIRE_REALTIME_VOICE")
    if (
        settings.multiagent_voice_enabled
        and not settings.realtime_voice_enabled
    ):
        raise ValueError("MULTIAGENT_VOICE_REQUIRES_REALTIME_VOICE")

    if not settings.oidc_user_claim:
        raise ValueError("PLATFORM_OIDC_USER_CLAIM_INVALID")
    if not settings.oidc_tenant_claim:
        raise ValueError("PLATFORM_OIDC_TENANT_CLAIM_INVALID")
    if not settings.oidc_roles_claim:
        raise ValueError("PLATFORM_OIDC_ROLES_CLAIM_INVALID")
    if not settings.oidc_member_roles:
        raise ValueError("PLATFORM_OIDC_MEMBER_ROLES_REQUIRED")
    if (
        settings.github_orion_auto_audit_enabled
        and not settings.github_integration_enabled
    ):
        raise ValueError(
            "PLATFORM_GITHUB_ORION_AUTO_AUDIT_REQUIRES_INTEGRATION"
        )
    if (
        settings.github_integration_enabled
        and not (
            settings.github_allow_metadata_read
            or settings.github_allow_content_read
        )
    ):
        raise ValueError(
            "PLATFORM_GITHUB_READ_PERMISSION_REQUIRED"
        )

    allowed_team_agents = {"Orion", "Chris", "Laura"}
    if any(
        agent_id not in allowed_team_agents
        for agent_id in settings.multiagent_team_agents
    ):
        raise ValueError("PLATFORM_MULTIAGENT_TEAM_AGENTS_INVALID")
    return settings
