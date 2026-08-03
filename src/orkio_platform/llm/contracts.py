from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator, Literal, Protocol, Sequence


LLMRole = Literal["user", "assistant"]
LLMStreamEventType = Literal["delta", "completed"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: LLMRole
    content: str


@dataclass(frozen=True, slots=True)
class LLMCompletionRequest:
    tenant_id: str
    user_id: str
    thread_id: str
    agent_id: str
    display_name: str
    system_prompt: str
    messages: tuple[LLMMessage, ...]


@dataclass(frozen=True, slots=True)
class LLMResult:
    content: str
    provider: str
    model: str
    response_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def token_usage(self) -> dict[str, int] | None:
        values = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
        }
        normalized = {
            key: value
            for key, value in values.items()
            if value is not None
        }
        return normalized or None


@dataclass(frozen=True, slots=True)
class LLMStreamEvent:
    event_type: LLMStreamEventType
    delta: str = ""
    result: LLMResult | None = None

    @classmethod
    def text_delta(cls, delta: str) -> "LLMStreamEvent":
        return cls(event_type="delta", delta=delta)

    @classmethod
    def completed(cls, result: LLMResult) -> "LLMStreamEvent":
        return cls(event_type="completed", result=result)


class LLMProviderError(Exception):
    def __init__(
        self,
        code: str,
        safe_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(safe_message)
        self.code = code
        self.safe_message = safe_message
        self.retryable = retryable


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def complete(
        self,
        request: LLMCompletionRequest,
    ) -> LLMResult: ...

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]: ...


def normalize_messages(
    messages: Sequence[LLMMessage],
) -> tuple[LLMMessage, ...]:
    normalized = tuple(
        LLMMessage(
            role=message.role,
            content=message.content.strip(),
        )
        for message in messages
        if message.content.strip()
    )
    if not normalized:
        raise ValueError("LLM_MESSAGES_REQUIRED")
    if normalized[-1].role != "user":
        raise ValueError("LLM_LAST_MESSAGE_MUST_BE_USER")
    return normalized
