from __future__ import annotations

import json
from collections.abc import Iterator

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import ChatRequest, PrincipalContext, SSEEvent, new_id


def encode_event(event: SSEEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"id: {event.event_id}\nevent: {event.event_type}\ndata: {payload}\n\n"


def stream_chat(
    service: PlatformService,
    principal: PrincipalContext,
    request: ChatRequest,
) -> Iterator[str]:
    context = service.prepare_turn(principal, request)
    sequence = 0

    def emit(event_type: str, payload: dict[str, object]) -> str:
        nonlocal sequence
        sequence += 1
        return encode_event(
            SSEEvent(
                event_id=f"{context.execution_id}:{sequence}",
                event_type=event_type,
                execution_id=context.execution_id,
                tenant_id=context.tenant_id,
                thread_id=context.thread_id,
                agent_id=context.turn_owner,
                turn_owner=context.turn_owner,
                sequence=sequence,
                payload=payload,
            )
        )

    try:
        yield emit("status", {"status": "stream_open"})
        yield emit(
            "execution",
            {
                "request_id": context.request_id,
                "route_family": context.route_family,
            },
        )
        yield emit(
            "agent_started",
            {
                "agent_id": context.turn_owner,
                "ownership_locked": context.ownership_locked,
            },
        )

        if request.simulate_error:
            raise RuntimeError("controlled")

        content = (
            f"[{context.turn_owner}] Resposta SSE determinística para "
            f"{context.tenant_id}."
        )
        yield emit("agent_chunk", {"content": content, "chunk_index": 0})
        yield emit(
            "agent_done",
            {
                "content_length": len(content),
                "agent_id": context.turn_owner,
            },
        )
        yield emit("done", {"outcome": "success"})
    except Exception:
        yield emit(
            "error",
            {
                "code": "SSE_GENERATOR_EXCEPTION",
                "message": "The realtime producer failed.",
            },
        )
        yield emit(
            "done",
            {
                "outcome": "error",
                "error_code": "SSE_GENERATOR_EXCEPTION",
            },
        )
