from types import SimpleNamespace

from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMMessage,
)
from orkio_platform.llm.openai_responses import (
    OpenAIResponsesProvider,
)


class FakeStream:
    def __init__(self, events):
        self.events = events
        self.closed = False

    def __iter__(self):
        return iter(self.events)

    def close(self):
        self.closed = True


class FakeResponses:
    def __init__(self, stream):
        self.stream = stream
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.stream


class FakeClient:
    def __init__(self, responses):
        self.responses = responses


def test_openai_responses_stream_maps_deltas_and_terminal_usage():
    response = SimpleNamespace(
        id="resp-stream",
        usage=SimpleNamespace(
            input_tokens=7,
            output_tokens=3,
            total_tokens=10,
        ),
        output_text="Olá mundo",
    )
    stream = FakeStream(
        [
            SimpleNamespace(
                type="response.output_text.delta",
                delta="Olá ",
            ),
            SimpleNamespace(
                type="response.output_text.delta",
                delta="mundo",
            ),
            SimpleNamespace(
                type="response.completed",
                response=response,
            ),
        ]
    )
    responses = FakeResponses(stream)
    provider = OpenAIResponsesProvider(
        api_key="not-a-real-key",
        model="approved-model",
        base_url="https://api.openai.com/v1",
        timeout_seconds=30,
        max_retries=1,
        max_output_tokens=100,
        store_responses=False,
        client=FakeClient(responses),
    )
    request = LLMCompletionRequest(
        tenant_id="tenant-a",
        user_id="user-a",
        thread_id="thread-a",
        agent_id="Orion",
        display_name="Orion",
        system_prompt="System",
        messages=(LLMMessage(role="user", content="Pergunta"),),
    )

    events = list(provider.stream(request))

    assert [event.event_type for event in events] == [
        "delta",
        "delta",
        "completed",
    ]
    assert [event.delta for event in events[:2]] == ["Olá ", "mundo"]
    assert events[-1].result is not None
    assert events[-1].result.content == "Olá mundo"
    assert events[-1].result.token_usage() == {
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
    }
    assert responses.calls[0]["stream"] is True
    assert responses.calls[0]["store"] is False
    assert stream.closed is True
