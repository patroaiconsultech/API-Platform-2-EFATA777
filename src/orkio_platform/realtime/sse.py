from __future__ import annotations

import json
from collections.abc import Iterator
from time import perf_counter

from orkio_platform.application.services import PlatformService
from orkio_platform.domain.errors import DomainError
from orkio_platform.domain.models import (
    ChatRequest,
    PrincipalContext,
    SSEEvent,
    new_id,
    utc_now,
)


def encode_event(event: SSEEvent) -> str:
    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"id: {event.event_id}\n"
        f"event: {event.event_type}\n"
        f"data: {payload}\n\n"
    )


def encode_pre_context_event(
    *,
    event_id: str,
    event_type: str,
    request_id: str,
    principal: PrincipalContext,
    request: ChatRequest,
    sequence: int,
    payload: dict[str, object],
) -> str:
    body = {
        "event_id": event_id,
        "event_type": event_type,
        "request_id": request_id,
        "execution_id": None,
        "tenant_id": principal.tenant_id,
        "thread_id": request.thread_id,
        "agent_id": request.requested_agent,
        "turn_owner": None,
        "sequence": sequence,
        "payload": payload,
        "created_at": utc_now().isoformat(),
        "context_status": "NOT_RESOLVED",
        "transport": "sse",
        "terminal_source": "wire",
    }
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (
        f"id: {event_id}\n"
        f"event: {event_type}\n"
        f"data: {encoded}\n\n"
    )


def stream_chat(
    service: PlatformService,
    principal: PrincipalContext,
    request: ChatRequest,
) -> Iterator[str]:
    started = perf_counter()
    request_id = request.request_id or new_id("request")
    effective_request = request.model_copy(
        update={"request_id": request_id},
    )
    pre_context_sequence = 0

    def emit_pre_context(
        event_type: str,
        payload: dict[str, object],
    ) -> str:
        nonlocal pre_context_sequence
        pre_context_sequence += 1
        return encode_pre_context_event(
            event_id=f"{request_id}:pre:{pre_context_sequence}",
            event_type=event_type,
            request_id=request_id,
            principal=principal,
            request=effective_request,
            sequence=pre_context_sequence,
            payload=payload,
        )

    try:
        context = service.prepare_turn(
            principal,
            effective_request,
        )
    except DomainError as exc:
        yield emit_pre_context(
            "error",
            {
                "code": exc.code,
                "message": exc.message,
                "phase": "prepare_turn",
            },
        )
        yield emit_pre_context(
            "done",
            {
                "outcome": "error",
                "error_code": exc.code,
                "phase": "prepare_turn",
            },
        )
        return
    except Exception:
        yield emit_pre_context(
            "error",
            {
                "code": "SSE_PRE_CONTEXT_EXCEPTION",
                "message": (
                    "The realtime context could not be resolved."
                ),
                "phase": "prepare_turn",
            },
        )
        yield emit_pre_context(
            "done",
            {
                "outcome": "error",
                "error_code": "SSE_PRE_CONTEXT_EXCEPTION",
                "phase": "prepare_turn",
            },
        )
        return

    sequence = 0

    def emit(
        event_type: str,
        payload: dict[str, object],
    ) -> str:
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
        context, execution, created = service.reserve_turn(
            context,
            effective_request,
        )
        yield emit(
            "status",
            {
                "status": "stream_open",
                "replayed": not created,
                "transport": "sse",
                "terminal_source": "wire",
            },
        )
        yield emit(
            "execution",
            {
                "request_id": context.request_id,
                "execution_id": context.execution_id,
                "route_family": context.route_family,
                "interaction_mode": context.interaction_mode,
                "contributing_agents": list(
                    context.contributing_agents
                ),
                "trace_kind": context.trace_kind,
                "replayed": not created,
                "transport": "sse",
                "terminal_source": "wire",
            },
        )
        yield emit(
            "agent_started",
            {
                "agent_id": context.turn_owner,
                "display_name": context.display_agent,
                "ownership_locked": context.ownership_locked,
                "interaction_mode": context.interaction_mode,
                "realtime_streaming": (
                    service.realtime_streaming_enabled
                ),
                "replayed": not created,
            },
        )

        if service.realtime_streaming_enabled:
            terminal_response = None
            terminal_replayed = False
            for signal in service.stream_reserved_turn(
                context,
                execution,
                effective_request,
                created=created,
                started=started,
            ):
                if signal.kind == "execution":
                    yield emit("execution", signal.payload)
                    phase = signal.payload.get("phase")
                    if phase == "node_started":
                        yield emit(
                            "agent_contribution_started",
                            signal.payload,
                        )
                    elif phase == "node_completed":
                        yield emit(
                            "agent_contribution_done",
                            signal.payload,
                        )
                    continue
                if signal.kind == "delta":
                    yield emit("agent_chunk", signal.payload)
                    continue
                if signal.kind == "terminal":
                    terminal_response = signal.response
                    terminal_replayed = bool(
                        signal.payload.get("replayed", False)
                    )

            if terminal_response is None:
                raise RuntimeError("STREAM_TERMINAL_RESPONSE_REQUIRED")

            response = terminal_response
            replayed = terminal_replayed
        else:
            response, replayed = service.execute_reserved_turn(
                context,
                execution,
                effective_request,
                created=created,
                started=started,
            )

        response = response.model_copy(
            update={
                "transport": "sse",
                "terminal_source": "wire",
            }
        )

        if response.status == "cancelled":
            yield emit(
                "cancelled",
                {
                    "message": response.model_dump(mode="json"),
                    "message_id": response.message_id,
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                },
            )
            yield emit(
                "done",
                {
                    "outcome": "cancelled",
                    "message_id": response.message_id,
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                    "done_observed": True,
                    "event_count": sequence + 1,
                    "last_event_id": (
                        f"{context.execution_id}:{sequence + 1}"
                    ),
                },
            )
            return

        if response.status == "partial":
            yield emit(
                "partial",
                {
                    "message": response.model_dump(mode="json"),
                    "message_id": response.message_id,
                    "reason": (
                        response.error or {}
                    ).get("code", "EXECUTION_PARTIAL"),
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                },
            )
            yield emit(
                "done",
                {
                    "outcome": "partial",
                    "message_id": response.message_id,
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                    "done_observed": True,
                    "event_count": sequence + 1,
                    "last_event_id": (
                        f"{context.execution_id}:{sequence + 1}"
                    ),
                },
            )
            return

        if response.status == "error":
            yield emit(
                "error",
                {
                    **(response.error or {}),
                    "message_id": response.message_id,
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                },
            )
            yield emit(
                "done",
                {
                    "outcome": "error",
                    "error_code": (
                        response.error or {}
                    ).get("code", "EXECUTION_FAILED"),
                    "message_id": response.message_id,
                    "replayed": replayed,
                    "transport": "sse",
                    "terminal_source": "wire",
                    "done_observed": True,
                    "event_count": sequence + 1,
                    "last_event_id": (
                        f"{context.execution_id}:{sequence + 1}"
                    ),
                },
            )
            return

        if not service.realtime_streaming_enabled:
            yield emit(
                "agent_chunk",
                {
                    "content": response.content,
                    "chunk_index": 0,
                    "replayed": replayed,
                },
            )
        yield emit(
            "agent_done",
            {
                "message": response.model_dump(mode="json"),
                "content_length": len(response.content),
                "agent_id": context.turn_owner,
                "replayed": replayed,
                "transport": "sse",
                "terminal_source": "wire",
                "agent_done_observed": True,
            },
        )
        yield emit(
            "done",
            {
                "outcome": "success",
                "message_id": response.message_id,
                "replayed": replayed,
                "transport": "sse",
                "terminal_source": "wire",
                "done_observed": True,
                "event_count": sequence + 1,
                "last_event_id": (
                    f"{context.execution_id}:{sequence + 1}"
                ),
            },
        )
    except DomainError as exc:
        yield emit(
            "error",
            {
                "code": exc.code,
                "message": exc.message,
            },
        )
        yield emit(
            "done",
            {
                "outcome": "error",
                "error_code": exc.code,
                "transport": "sse",
                "terminal_source": "wire",
                "done_observed": True,
                "event_count": sequence + 1,
                "last_event_id": (
                    f"{context.execution_id}:{sequence + 1}"
                ),
            },
        )
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
                "transport": "sse",
                "terminal_source": "wire",
                "done_observed": True,
                "event_count": sequence + 1,
                "last_event_id": (
                    f"{context.execution_id}:{sequence + 1}"
                ),
            },
        )
