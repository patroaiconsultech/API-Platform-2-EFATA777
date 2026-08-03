from __future__ import annotations

from collections.abc import Iterator

from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMResult,
    LLMStreamEvent,
)


class DeterministicLLMProvider:
    provider_name = "deterministic"
    model_name = "local-deterministic"

    def complete(
        self,
        request: LLMCompletionRequest,
    ) -> LLMResult:
        return LLMResult(
            content=(
                f"[{request.display_name}] Recebi sua mensagem no tenant "
                f"{request.tenant_id}. RC1 opera com provider "
                "determinístico local."
            ),
            provider=self.provider_name,
            model=self.model_name,
        )

    def stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        result = self.complete(request)
        words = result.content.split(" ")
        for index, word in enumerate(words):
            suffix = "" if index == len(words) - 1 else " "
            yield LLMStreamEvent.text_delta(word + suffix)
        yield LLMStreamEvent.completed(result)
