from dataclasses import replace
from types import SimpleNamespace

import pytest

from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMMessage,
    LLMProviderError,
)
from orkio_platform.llm.openai_responses import (
    OpenAIResponsesProvider,
)


class FakeResponses:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.result


class FakeClient:
    def __init__(self, responses):
        self.responses = responses


def request():
    return LLMCompletionRequest(
        tenant_id="tenant-a",
        user_id="user-a",
        thread_id="thread-a",
        agent_id="Orion",
        display_name="Orion",
        system_prompt="System instructions.",
        messages=(
            LLMMessage(role="user", content="Pergunta"),
        ),
    )


def provider(responses):
    return OpenAIResponsesProvider(
        api_key="not-sent-to-fake",
        model="approved-model",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        max_retries=1,
        max_output_tokens=1000,
        store_responses=False,
        client=FakeClient(responses),
    )


def test_openai_responses_request_and_usage_mapping():
    responses = FakeResponses(
        result=SimpleNamespace(
            id="resp_123",
            output_text="Resposta real.",
            usage=SimpleNamespace(
                input_tokens=10,
                output_tokens=5,
                total_tokens=15,
            ),
        )
    )
    result = provider(responses).complete(request())

    assert result.content == "Resposta real."
    assert result.provider == "openai_responses"
    assert result.model == "approved-model"
    assert result.response_id == "resp_123"
    assert result.token_usage() == {
        "input_tokens": 10,
        "output_tokens": 5,
        "total_tokens": 15,
    }

    call = responses.calls[0]
    assert call["model"] == "approved-model"
    assert call["instructions"] == "System instructions."
    assert call["input"] == [
        {"role": "user", "content": "Pergunta"}
    ]
    assert call["max_output_tokens"] == 1000
    assert call["store"] is False
    assert "tenant_id" not in call
    assert "user_id" not in call
    assert "metadata" not in call


def test_empty_provider_response_fails_closed():
    responses = FakeResponses(
        result=SimpleNamespace(
            id="resp_empty",
            output_text="  ",
            usage=None,
        )
    )
    with pytest.raises(LLMProviderError) as captured:
        provider(responses).complete(request())
    assert captured.value.code == "LLM_PROVIDER_EMPTY_RESPONSE"
    assert captured.value.retryable is False


def test_rate_limit_is_mapped_to_safe_retryable_error():
    class RateLimitError(Exception):
        status_code = 429

    responses = FakeResponses(error=RateLimitError("raw upstream secret"))
    with pytest.raises(LLMProviderError) as captured:
        provider(responses).complete(request())

    assert captured.value.code == "LLM_PROVIDER_RATE_LIMITED"
    assert captured.value.retryable is True
    assert "raw upstream secret" not in captured.value.safe_message


def test_provider_rejects_history_without_terminal_user_message():
    responses = FakeResponses()
    invalid = replace(
        request(),
        messages=(
            LLMMessage(role="assistant", content="Resposta antiga"),
        ),
    )
    with pytest.raises(ValueError, match="LLM_LAST_MESSAGE_MUST_BE_USER"):
        provider(responses).complete(invalid)
    assert responses.calls == []
