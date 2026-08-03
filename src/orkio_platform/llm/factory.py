from orkio_platform.config import Settings
from orkio_platform.llm.contracts import LLMProvider
from orkio_platform.llm.deterministic import DeterministicLLMProvider
from orkio_platform.llm.openai_responses import OpenAIResponsesProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm_provider == "deterministic":
        return DeterministicLLMProvider()

    if settings.llm_provider == "openai_responses":
        assert settings.openai_api_key is not None
        assert settings.openai_default_model is not None
        return OpenAIResponsesProvider(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_default_model,
            base_url=settings.openai_base_url,
            timeout_seconds=settings.openai_timeout_seconds,
            max_retries=settings.openai_max_retries,
            max_output_tokens=settings.openai_max_output_tokens,
            store_responses=settings.openai_store_responses,
            organization_id=settings.openai_organization_id,
            project_id=settings.openai_project_id,
        )

    raise ValueError("PLATFORM_LLM_PROVIDER_INVALID")
