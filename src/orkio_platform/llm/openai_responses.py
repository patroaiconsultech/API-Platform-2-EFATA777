from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMProviderError,
    LLMResult,
    LLMStreamEvent,
    normalize_messages,
)


def _integer_attribute(value: object, name: str) -> int | None:
    candidate = getattr(value, name, None)
    if isinstance(candidate, bool):
        return None
    return candidate if isinstance(candidate, int) else None


def _response_result(
    *,
    response: object | None,
    content: str,
    provider: str,
    model: str,
) -> LLMResult:
    usage = getattr(response, "usage", None)
    return LLMResult(
        content=content.strip(),
        provider=provider,
        model=model,
        response_id=getattr(response, "id", None),
        input_tokens=(
            _integer_attribute(usage, "input_tokens")
            if usage is not None
            else None
        ),
        output_tokens=(
            _integer_attribute(usage, "output_tokens")
            if usage is not None
            else None
        ),
        total_tokens=(
            _integer_attribute(usage, "total_tokens")
            if usage is not None
            else None
        ),
    )


class OpenAIResponsesProvider:
    provider_name = "openai_responses"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: int,
        max_retries: int,
        max_output_tokens: int,
        store_responses: bool,
        organization_id: str | None = None,
        project_id: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model_name = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_output_tokens = max_output_tokens
        self._store_responses = store_responses
        self._organization_id = organization_id
        self._project_id = project_id
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client

        try:
            from openai import OpenAI
        except ImportError as exc:
            raise LLMProviderError(
                "LLM_PROVIDER_SDK_MISSING",
                "The configured LLM provider SDK is not installed.",
                retryable=False,
            ) from exc

        options: dict[str, object] = {
            "api_key": self._api_key,
            "base_url": self._base_url,
            "timeout": self._timeout_seconds,
            "max_retries": self._max_retries,
        }
        if self._organization_id:
            options["organization"] = self._organization_id
        if self._project_id:
            options["project"] = self._project_id

        self._client = OpenAI(**options)
        return self._client

    @staticmethod
    def _map_exception(exc: Exception) -> LLMProviderError:
        class_name = exc.__class__.__name__
        status_code = getattr(exc, "status_code", None)

        if class_name in {"APITimeoutError", "TimeoutException"}:
            return LLMProviderError(
                "LLM_PROVIDER_TIMEOUT",
                "The language model provider timed out.",
                retryable=True,
            )
        if class_name in {
            "APIConnectionError",
            "ConnectError",
            "ConnectionError",
        }:
            return LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The language model provider is unavailable.",
                retryable=True,
            )
        if class_name == "RateLimitError" or status_code == 429:
            return LLMProviderError(
                "LLM_PROVIDER_RATE_LIMITED",
                "The language model provider rate limit was reached.",
                retryable=True,
            )
        if status_code in {401, 403}:
            return LLMProviderError(
                "LLM_PROVIDER_AUTH_FAILED",
                "The language model provider rejected its credentials.",
                retryable=False,
            )
        if isinstance(status_code, int) and status_code >= 500:
            return LLMProviderError(
                "LLM_PROVIDER_UNAVAILABLE",
                "The language model provider is unavailable.",
                retryable=True,
            )
        return LLMProviderError(
            "LLM_PROVIDER_REQUEST_FAILED",
            "The language model provider rejected the request.",
            retryable=False,
        )

    def _request_arguments(
        self,
        request: LLMCompletionRequest,
    ) -> dict[str, object]:
        messages = normalize_messages(request.messages)
        return {
            "model": self.model_name,
            "instructions": request.system_prompt,
            "input": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
            "max_output_tokens": self._max_output_tokens,
            "store": self._store_responses,
        }

    def complete(
        self,
        request: LLMCompletionRequest,
    ) -> LLMResult:
        arguments = self._request_arguments(request)
        try:
            response = self._get_client().responses.create(
                **arguments,
            )
        except LLMProviderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

        content = getattr(response, "output_text", None)
        if callable(content):
            content = content()
        if not isinstance(content, str) or not content.strip():
            raise LLMProviderError(
                "LLM_PROVIDER_EMPTY_RESPONSE",
                "The language model provider returned no text.",
                retryable=False,
            )

        return _response_result(
            response=response,
            content=content,
            provider=self.provider_name,
            model=self.model_name,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        arguments = self._request_arguments(request)
        try:
            stream = self._get_client().responses.create(
                **arguments,
                stream=True,
            )
        except LLMProviderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc

        content_parts: list[str] = []
        terminal_response: object | None = None
        try:
            for event in stream:
                event_type = getattr(event, "type", "")
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if isinstance(delta, str) and delta:
                        content_parts.append(delta)
                        yield LLMStreamEvent.text_delta(delta)
                    continue

                if event_type == "response.completed":
                    terminal_response = getattr(event, "response", None)
                    continue

                if event_type in {
                    "response.failed",
                    "response.incomplete",
                    "error",
                }:
                    raise LLMProviderError(
                        "LLM_PROVIDER_REQUEST_FAILED",
                        "The language model provider could not complete the response.",
                        retryable=event_type != "response.incomplete",
                    )
        except LLMProviderError:
            raise
        except Exception as exc:
            raise self._map_exception(exc) from exc
        finally:
            close = getattr(stream, "close", None)
            if callable(close):
                close()

        content = "".join(content_parts).strip()
        if not content and terminal_response is not None:
            terminal_text = getattr(terminal_response, "output_text", None)
            if callable(terminal_text):
                terminal_text = terminal_text()
            if isinstance(terminal_text, str):
                content = terminal_text.strip()

        if not content:
            raise LLMProviderError(
                "LLM_PROVIDER_EMPTY_RESPONSE",
                "The language model provider returned no text.",
                retryable=False,
            )

        yield LLMStreamEvent.completed(
            _response_result(
                response=terminal_response,
                content=content,
                provider=self.provider_name,
                model=self.model_name,
            )
        )
