import pytest
from pydantic import SecretStr

from orkio_platform.config import get_settings


LLM_ENV_NAMES = (
    "PLATFORM_LLM_PROVIDER",
    "PLATFORM_LLM_HISTORY_MESSAGES",
    "PLATFORM_LLM_MAX_CONTEXT_CHARS",
    "OPENAI_API_KEY",
    "OPENAI_DEFAULT_MODEL",
    "OPENAI_BASE_URL",
    "OPENAI_ORGANIZATION_ID",
    "OPENAI_PROJECT_ID",
    "OPENAI_TIMEOUT_SECONDS",
    "OPENAI_MAX_RETRIES",
    "OPENAI_MAX_OUTPUT_TOKENS",
    "OPENAI_STORE_RESPONSES",
)


def clear_llm_env(monkeypatch):
    for name in LLM_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
    get_settings.cache_clear()


def test_llm_defaults_to_deterministic_without_secret(monkeypatch):
    clear_llm_env(monkeypatch)
    settings = get_settings()
    assert settings.llm_provider == "deterministic"
    assert settings.openai_api_key is None
    assert settings.openai_default_model is None
    assert settings.llm_history_messages == 20
    assert settings.openai_store_responses is False


def test_openai_provider_requires_api_key(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "openai_responses")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "approved-model")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="OPENAI_API_KEY_REQUIRED"):
        get_settings()


def test_openai_provider_requires_model(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "openai_responses")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="OPENAI_DEFAULT_MODEL_REQUIRED"):
        get_settings()


def test_openai_base_url_requires_https_in_production(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("PLATFORM_ENVIRONMENT", "production")
    monkeypatch.setenv("PLATFORM_AUTH_MODE", "external_required")
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "openai_responses")
    monkeypatch.setenv("OPENAI_API_KEY", "secret-value")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "approved-model")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.invalid/v1")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="OPENAI_BASE_URL_HTTPS_REQUIRED"):
        get_settings()


def test_openai_configuration_is_typed_and_secret_is_redacted(monkeypatch):
    clear_llm_env(monkeypatch)
    monkeypatch.setenv("PLATFORM_LLM_PROVIDER", "openai_responses")
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret-openai-key")
    monkeypatch.setenv("OPENAI_DEFAULT_MODEL", "approved-model")
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "90")
    monkeypatch.setenv("OPENAI_MAX_RETRIES", "1")
    monkeypatch.setenv("OPENAI_MAX_OUTPUT_TOKENS", "2048")
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.llm_provider == "openai_responses"
    assert isinstance(settings.openai_api_key, SecretStr)
    assert settings.openai_api_key.get_secret_value() == (
        "super-secret-openai-key"
    )
    assert "super-secret-openai-key" not in repr(settings)
    assert settings.openai_default_model == "approved-model"
    assert settings.openai_timeout_seconds == 90
    assert settings.openai_max_retries == 1
    assert settings.openai_max_output_tokens == 2048
