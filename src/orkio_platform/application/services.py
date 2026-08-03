from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta, timezone
from time import perf_counter

from orkio_platform.application.catalog import resolve_agent
from orkio_platform.application.streaming import TurnStreamSignal
from orkio_platform.llm.contracts import (
    LLMCompletionRequest,
    LLMMessage,
    LLMProvider,
    LLMProviderError,
    LLMResult,
    LLMStreamEvent,
)
from orkio_platform.llm.deterministic import (
    DeterministicLLMProvider,
)
from orkio_platform.llm.prompts import (
    contribution_prompt_for_agent,
    synthesis_prompt_for_agent,
    system_prompt_for_agent,
)
from orkio_platform.domain.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
)
from orkio_platform.domain.models import (
    AgentTurnContext,
    ChatRequest,
    ExecutionRecord,
    MessageRecord,
    PrincipalContext,
    RecoveryDecisionCreate,
    RecoveryDecisionRecord,
    ResponseEnvelope,
    ThreadRecord,
    new_id,
    utc_now,
)
from orkio_platform.infrastructure.repository_protocol import (
    RepositoryProtocol,
)
from orkio_platform.observability.execution import log_execution_event
from orkio_platform.orchestration.contracts import AgentContribution
from orkio_platform.orchestration.router import build_orchestration_plan


class PlatformService:
    def __init__(
        self,
        repository: RepositoryProtocol,
        *,
        execution_lease_seconds: int = 60,
        execution_stale_after_seconds: int = 300,
        llm_provider: LLMProvider | None = None,
        llm_history_messages: int = 20,
        llm_max_context_chars: int = 100_000,
        realtime_streaming_enabled: bool = False,
        multiagent_enabled: bool = False,
        multiagent_max_contributors: int = 2,
        multiagent_team_agents: tuple[str, ...] = (
            "Orion",
            "Chris",
            "Laura",
        ),
    ) -> None:
        if execution_lease_seconds <= 0:
            raise ValueError("EXECUTION_LEASE_THRESHOLD_INVALID")
        if execution_stale_after_seconds < execution_lease_seconds:
            raise ValueError("EXECUTION_STALE_THRESHOLD_INVALID")
        self.repository = repository
        self.execution_lease_seconds = execution_lease_seconds
        self.execution_stale_after_seconds = (
            execution_stale_after_seconds
        )
        if llm_history_messages < 0:
            raise ValueError("LLM_HISTORY_MESSAGES_INVALID")
        if llm_max_context_chars < 1_000:
            raise ValueError("LLM_MAX_CONTEXT_CHARS_INVALID")
        self.llm_provider = (
            llm_provider or DeterministicLLMProvider()
        )
        self.llm_history_messages = llm_history_messages
        self.llm_max_context_chars = llm_max_context_chars
        if multiagent_max_contributors < 0:
            raise ValueError("MULTIAGENT_MAX_CONTRIBUTORS_INVALID")
        self.realtime_streaming_enabled = realtime_streaming_enabled
        self.multiagent_enabled = multiagent_enabled
        self.multiagent_max_contributors = multiagent_max_contributors
        self.multiagent_team_agents = multiagent_team_agents

    def create_thread(
        self,
        principal: PrincipalContext,
        title: str,
    ) -> ThreadRecord:
        return self.repository.create_thread(
            ThreadRecord(
                thread_id=new_id("thread"),
                tenant_id=principal.tenant_id,
                created_by=principal.user_id,
                title=title,
            )
        )

    def list_threads(
        self,
        principal: PrincipalContext,
    ) -> list[ThreadRecord]:
        return self.repository.list_threads(principal.tenant_id)

    def list_messages(
        self,
        principal: PrincipalContext,
        thread_id: str,
    ) -> list[MessageRecord]:
        return self.repository.list_messages(
            principal.tenant_id,
            thread_id,
        )

    def prepare_turn(
        self,
        principal: PrincipalContext,
        request: ChatRequest,
    ) -> AgentTurnContext:
        self.repository.get_thread(
            principal.tenant_id,
            request.thread_id,
        )
        plan = build_orchestration_plan(
            request.requested_agent,
            request.content,
            enabled=self.multiagent_enabled,
            max_contributors=self.multiagent_max_contributors,
            team_agents=self.multiagent_team_agents,
        )
        owner = resolve_agent(plan.owner_agent)
        return AgentTurnContext(
            request_id=request.request_id or new_id("request"),
            execution_id=new_id("execution"),
            thread_id=request.thread_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            requested_agent=plan.requested_agent,
            resolved_agent=owner.agent_id,
            turn_owner=owner.agent_id,
            display_agent=owner.display_name,
            route_family=plan.route_family,
            contributing_agents=plan.contributors,
            trace_kind=plan.trace_kind,
        )

    @staticmethod
    def request_fingerprint(
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> str:
        payload = {
            "thread_id": context.thread_id,
            "user_id": context.user_id,
            "requested_agent": context.requested_agent,
            "resolved_agent": context.resolved_agent,
            "turn_owner": context.turn_owner,
            "contributing_agents": context.contributing_agents,
            "route_family": context.route_family,
            "content": request.content,
            "simulate_error": request.simulate_error,
        }
        canonical = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _aware(value):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value

    def reserve_turn(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[AgentTurnContext, ExecutionRecord, bool]:
        now = utc_now()
        candidate = ExecutionRecord(
            tenant_id=context.tenant_id,
            request_id=context.request_id,
            execution_id=context.execution_id,
            thread_id=context.thread_id,
            user_id=context.user_id,
            requested_agent=context.requested_agent,
            resolved_agent=context.resolved_agent,
            turn_owner=context.turn_owner,
            display_name=context.display_agent,
            route_family=context.route_family,
            request_fingerprint_sha256=self.request_fingerprint(
                context,
                request,
            ),
            lease_owner=context.execution_id,
            heartbeat_at=now,
            lease_expires_at=now
            + timedelta(seconds=self.execution_lease_seconds),
            started_at=now,
        )
        execution, created = self.repository.reserve_execution(candidate)
        if (
            execution.request_fingerprint_sha256
            != candidate.request_fingerprint_sha256
        ):
            raise ConflictError(
                "IDEMPOTENCY_KEY_REUSED",
                "The request ID is already bound to another request.",
            )

        if not created and execution.status == "running":
            now = utc_now()
            lease_expired = (
                now >= self._aware(execution.lease_expires_at)
            )
            started_age = (
                now - self._aware(execution.started_at)
            ).total_seconds()
            if (
                lease_expired
                or started_age
                >= self.execution_stale_after_seconds
            ):
                log_execution_event(
                    "execution_stale_detected",
                    execution,
                    automatic_recovery=False,
                )
                raise ConflictError(
                    "STALE_EXECUTION_REQUIRES_RECOVERY",
                    "The running execution expired and requires governed recovery.",
                )

        effective_context = context.model_copy(
            update={
                "execution_id": execution.execution_id,
                "thread_id": execution.thread_id,
                "user_id": execution.user_id,
                "requested_agent": execution.requested_agent,
                "resolved_agent": execution.resolved_agent,
                "turn_owner": execution.turn_owner,
                "display_agent": execution.display_name,
                "route_family": execution.route_family,
            }
        )
        log_execution_event(
            "execution_reserved" if created else "execution_replayed",
            execution,
            created=created,
        )
        return effective_context, execution, created

    def heartbeat_turn(
        self,
        execution: ExecutionRecord,
    ) -> ExecutionRecord:
        now = utc_now()
        refreshed = self.repository.heartbeat_execution(
            execution.tenant_id,
            execution.request_id,
            lease_owner=execution.lease_owner,
            heartbeat_at=now,
            lease_expires_at=now
            + timedelta(seconds=self.execution_lease_seconds),
        )
        log_execution_event(
            "execution_heartbeat",
            refreshed,
            lease_expires_at=refreshed.lease_expires_at.isoformat(),
        )
        return refreshed

    def _user_message(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> MessageRecord:
        return MessageRecord(
            message_id=new_id("message"),
            request_id=context.request_id,
            execution_id=context.execution_id,
            thread_id=context.thread_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            role="user",
            content=request.content,
            route_family=context.route_family,
            status="success",
        )

    def _assistant_message(
        self,
        context: AgentTurnContext,
        content: str,
        *,
        status: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> MessageRecord:
        return MessageRecord(
            message_id=new_id("message"),
            request_id=context.request_id,
            execution_id=context.execution_id,
            thread_id=context.thread_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            role="assistant",
            content=content,
            agent_id=context.turn_owner,
            agent_name=context.turn_owner,
            display_name=context.display_agent,
            final_speaker=context.turn_owner,
            turn_owner=context.turn_owner,
            route_family=context.route_family,
            status=status,
            error_code=error_code,
            error_message=error_message,
        )

    def _history_messages(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[LLMMessage, ...]:
        persisted = self.repository.list_messages(
            context.tenant_id,
            context.thread_id,
        )
        eligible = [
            LLMMessage(
                role=message.role,
                content=message.content,
            )
            for message in persisted
            if message.role in {"user", "assistant"}
            and message.content.strip()
            and message.status not in {"error", "cancelled"}
        ]
        if self.llm_history_messages == 0:
            eligible = []
        else:
            eligible = eligible[-self.llm_history_messages :]

        current = LLMMessage(
            role="user",
            content=request.content,
        )
        selected: list[LLMMessage] = [current]
        used_chars = len(current.content)

        for message in reversed(eligible):
            message_chars = len(message.content)
            if used_chars + message_chars > self.llm_max_context_chars:
                break
            selected.append(message)
            used_chars += message_chars

        selected.reverse()
        return tuple(selected)

    def _llm_request_for_agent(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        *,
        agent_id: str,
        system_prompt: str,
    ) -> LLMCompletionRequest:
        agent = resolve_agent(agent_id)
        return LLMCompletionRequest(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            thread_id=context.thread_id,
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            system_prompt=system_prompt,
            messages=self._history_messages(context, request),
        )

    def _contribution_request(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributor_id: str,
    ) -> LLMCompletionRequest:
        contributor = resolve_agent(contributor_id)
        return self._llm_request_for_agent(
            context,
            request,
            agent_id=contributor.agent_id,
            system_prompt=contribution_prompt_for_agent(contributor),
        )

    def _owner_request(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributions: tuple[AgentContribution, ...],
    ) -> LLMCompletionRequest:
        owner = resolve_agent(context.turn_owner)
        return self._llm_request_for_agent(
            context,
            request,
            agent_id=owner.agent_id,
            system_prompt=synthesis_prompt_for_agent(
                owner,
                contributions,
            ),
        )

    @staticmethod
    def _contribution_from_result(
        agent_id: str,
        result: LLMResult,
    ) -> AgentContribution:
        agent = resolve_agent(agent_id)
        return AgentContribution(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            content=result.content,
            provider=result.provider,
            model=result.model,
            response_id=result.response_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )

    def generate_contributions(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[AgentContribution, ...]:
        contributions: list[AgentContribution] = []
        for contributor_id in context.contributing_agents:
            result = self.llm_provider.complete(
                self._contribution_request(
                    context,
                    request,
                    contributor_id,
                )
            )
            contributions.append(
                self._contribution_from_result(
                    contributor_id,
                    result,
                )
            )
        return tuple(contributions)

    def generate_content(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[LLMResult, tuple[AgentContribution, ...]]:
        contributions = self.generate_contributions(
            context,
            request,
        )
        result = self.llm_provider.complete(
            self._owner_request(
                context,
                request,
                contributions,
            )
        )
        return result, contributions

    @staticmethod
    def _aggregate_token_usage(
        contributions: tuple[AgentContribution, ...],
        owner_result: LLMResult | None,
    ) -> dict[str, int] | None:
        totals = {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }
        observed = False
        for usage in [
            *(item.token_usage() for item in contributions),
            (
                owner_result.token_usage()
                if owner_result is not None
                else None
            ),
        ]:
            if usage is None:
                continue
            observed = True
            for key in totals:
                value = usage.get(key)
                if isinstance(value, int):
                    totals[key] += value
        return totals if observed else None

    @staticmethod
    def _execution_trace(
        context: AgentTurnContext,
        contributions: tuple[AgentContribution, ...],
        owner_result: LLMResult | None,
    ) -> list[dict[str, object]]:
        trace: list[dict[str, object]] = []
        for index, item in enumerate(contributions):
            trace.append(
                {
                    "node_id": (
                        f"{context.execution_id}:contributor:{index}"
                    ),
                    "agent_id": item.agent_id,
                    "role": "contributor",
                    "status": "success",
                    "trace_kind": context.trace_kind,
                    "provider": item.provider,
                    "model": item.model,
                    "token_usage": item.token_usage(),
                }
            )
        trace.append(
            {
                "node_id": f"{context.execution_id}:owner",
                "agent_id": context.turn_owner,
                "role": "owner",
                "status": (
                    "success"
                    if owner_result is not None
                    else "unknown"
                ),
                "trace_kind": context.trace_kind,
                "provider": (
                    owner_result.provider
                    if owner_result is not None
                    else self.llm_provider.provider_name
                ),
                "model": (
                    owner_result.model
                    if owner_result is not None
                    else self.llm_provider.model_name
                ),
                "token_usage": (
                    owner_result.token_usage()
                    if owner_result is not None
                    else None
                ),
            }
        )
        return trace

    def _provider_stream(
        self,
        request: LLMCompletionRequest,
    ) -> Iterator[LLMStreamEvent]:
        stream_method = getattr(self.llm_provider, "stream", None)
        if callable(stream_method):
            yield from stream_method(request)
            return

        result = self.llm_provider.complete(request)
        yield LLMStreamEvent.text_delta(result.content)
        yield LLMStreamEvent.completed(result)

    def response_from_execution(
        self,
        execution: ExecutionRecord,
        *,
        latency_ms: int | None = None,
    ) -> ResponseEnvelope:
        if execution.status == "running":
            raise ConflictError(
                "REQUEST_IN_PROGRESS",
                "A request with this ID is still running.",
            )
        message: MessageRecord | None = None
        if execution.assistant_message_id:
            message = self.repository.get_message(
                execution.tenant_id,
                execution.assistant_message_id,
            )
        content = "" if message is None else message.content
        error = None
        if execution.status == "error":
            error = {
                "code": execution.error_code or "EXECUTION_FAILED",
                "message": (
                    execution.error_message
                    or "The execution ended with an error."
                ),
            }
        return ResponseEnvelope(
            message_id=(
                execution.assistant_message_id
                or f"{execution.execution_id}:terminal"
            ),
            request_id=execution.request_id,
            execution_id=execution.execution_id,
            thread_id=execution.thread_id,
            tenant_id=execution.tenant_id,
            agent_id=execution.turn_owner,
            agent_name=execution.turn_owner,
            display_name=execution.display_name,
            final_speaker=execution.turn_owner,
            turn_owner=execution.turn_owner,
            route_family=execution.route_family,
            content=content,
            status=execution.status,
            error=error,
            latency_ms=latency_ms,
        )

    def execute_reserved_turn(
        self,
        context: AgentTurnContext,
        execution: ExecutionRecord,
        request: ChatRequest,
        *,
        created: bool,
        started: float,
    ) -> tuple[ResponseEnvelope, bool]:
        if not created:
            return (
                self.response_from_execution(
                    execution,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
                True,
            )

        execution = self.heartbeat_turn(execution)
        user_message = self._user_message(context, request)

        if request.simulate_error:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code="SIMULATED_CHAT_FAILURE",
                error_message=(
                    "Controlled RC1 Premium Hardening failure."
                ),
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            log_execution_event(
                "execution_terminal_error",
                failed,
                error_code=failed.error_code,
            )
            return (
                self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
                False,
            )

        provider_result: LLMResult | None = None
        contributions: tuple[AgentContribution, ...] = ()
        try:
            provider_result, contributions = self.generate_content(
                context,
                request,
            )
            content = provider_result.content
        except LLMProviderError as exc:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code=exc.code,
                error_message=exc.safe_message,
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            log_execution_event(
                "execution_terminal_error",
                failed,
                error_code=failed.error_code,
                provider=self.llm_provider.provider_name,
                retryable=exc.retryable,
            )
            return (
                self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
                False,
            )
        except Exception:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code="PROVIDER_EXECUTION_FAILED",
                error_message="The provider execution failed.",
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            log_execution_event(
                "execution_terminal_error",
                failed,
                error_code=failed.error_code,
                provider=self.llm_provider.provider_name,
            )
            return (
                self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
                False,
            )

        execution = self.heartbeat_turn(execution)
        current = self.repository.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        if current is not None and current.status == "cancelled":
            log_execution_event(
                "execution_cancel_observed",
                current,
            )
            return (
                self.response_from_execution(
                    current,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
                False,
            )

        assistant_message = self._assistant_message(
            context,
            content,
            status="success",
        )
        try:
            completed = self.repository.complete_execution(
                execution,
                user_message,
                assistant_message,
            )
        except Exception as exc:
            current = self.repository.get_execution(
                execution.tenant_id,
                execution.request_id,
            )
            if current is not None and current.status == "cancelled":
                return (
                    self.response_from_execution(
                        current,
                        latency_ms=int(
                            (perf_counter() - started) * 1000
                        ),
                    ),
                    False,
                )
            try:
                self.repository.abort_execution(
                    execution.tenant_id,
                    execution.request_id,
                    error_code="TURN_PERSISTENCE_FAILED",
                    error_message=(
                        "The turn could not be persisted atomically."
                    ),
                )
            except Exception:
                pass
            raise ServiceUnavailableError(
                "TURN_PERSISTENCE_FAILED",
                "The turn could not be persisted atomically.",
            ) from exc

        token_usage = self._aggregate_token_usage(
            contributions,
            provider_result,
        )
        execution_trace = self._execution_trace(
            context,
            contributions,
            provider_result,
        )
        log_execution_event(
            "execution_terminal_success",
            completed,
            provider=(
                provider_result.provider
                if provider_result is not None
                else self.llm_provider.provider_name
            ),
            model=(
                provider_result.model
                if provider_result is not None
                else self.llm_provider.model_name
            ),
            token_usage=token_usage,
            provider_response_id=(
                provider_result.response_id
                if provider_result is not None
                else None
            ),
        )
        response = self.response_from_execution(
            completed,
            latency_ms=int((perf_counter() - started) * 1000),
        )
        response_updates: dict[str, object] = {
            "execution_trace": execution_trace,
        }
        if token_usage is not None:
            response_updates["token_usage"] = token_usage
        response = response.model_copy(update=response_updates)
        return (response, False)


    def stream_reserved_turn(
        self,
        context: AgentTurnContext,
        execution: ExecutionRecord,
        request: ChatRequest,
        *,
        created: bool,
        started: float,
    ) -> Iterator[TurnStreamSignal]:
        if not created:
            response = self.response_from_execution(
                execution,
                latency_ms=int((perf_counter() - started) * 1000),
            )
            if response.status == "success" and response.content:
                yield TurnStreamSignal(
                    kind="delta",
                    payload={
                        "content": response.content,
                        "chunk_index": 0,
                        "replayed": True,
                    },
                )
            yield TurnStreamSignal(
                kind="terminal",
                payload={"replayed": True},
                response=response,
            )
            return

        execution = self.heartbeat_turn(execution)
        user_message = self._user_message(context, request)

        if request.simulate_error:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code="SIMULATED_CHAT_FAILURE",
                error_message=(
                    "Controlled RC1 Premium Hardening failure."
                ),
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            yield TurnStreamSignal(
                kind="terminal",
                payload={"replayed": False},
                response=self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
            )
            return

        contributions: list[AgentContribution] = []
        owner_result: LLMResult | None = None
        chunks: list[str] = []
        chunk_index = 0

        try:
            for index, contributor_id in enumerate(
                context.contributing_agents
            ):
                current = self.repository.get_execution(
                    execution.tenant_id,
                    execution.request_id,
                )
                if current is not None and current.status == "cancelled":
                    yield TurnStreamSignal(
                        kind="terminal",
                        payload={"replayed": False},
                        response=self.response_from_execution(
                            current,
                            latency_ms=int(
                                (perf_counter() - started) * 1000
                            ),
                        ),
                    )
                    return

                node_id = (
                    f"{context.execution_id}:contributor:{index}"
                )
                yield TurnStreamSignal(
                    kind="execution",
                    payload={
                        "phase": "node_started",
                        "node_id": node_id,
                        "agent_id": contributor_id,
                        "role": "contributor",
                        "trace_kind": context.trace_kind,
                    },
                )
                result = self.llm_provider.complete(
                    self._contribution_request(
                        context,
                        request,
                        contributor_id,
                    )
                )
                contribution = self._contribution_from_result(
                    contributor_id,
                    result,
                )
                contributions.append(contribution)
                yield TurnStreamSignal(
                    kind="execution",
                    payload={
                        "phase": "node_completed",
                        "node_id": node_id,
                        "agent_id": contributor_id,
                        "role": "contributor",
                        "trace_kind": context.trace_kind,
                        "content": contribution.content,
                        "token_usage": contribution.token_usage(),
                    },
                )

            owner_request = self._owner_request(
                context,
                request,
                tuple(contributions),
            )
            provider_stream = self._provider_stream(owner_request)
            try:
                for event in provider_stream:
                    current = self.repository.get_execution(
                        execution.tenant_id,
                        execution.request_id,
                    )
                    if (
                        current is not None
                        and current.status == "cancelled"
                    ):
                        close = getattr(
                            provider_stream,
                            "close",
                            None,
                        )
                        if callable(close):
                            close()
                        yield TurnStreamSignal(
                            kind="terminal",
                            payload={"replayed": False},
                            response=self.response_from_execution(
                                current,
                                latency_ms=int(
                                    (perf_counter() - started) * 1000
                                ),
                            ),
                        )
                        return

                    if event.event_type == "delta":
                        if not event.delta:
                            continue
                        chunks.append(event.delta)
                        yield TurnStreamSignal(
                            kind="delta",
                            payload={
                                "content": event.delta,
                                "chunk_index": chunk_index,
                                "replayed": False,
                            },
                        )
                        chunk_index += 1
                    elif event.event_type == "completed":
                        owner_result = event.result
            finally:
                close = getattr(provider_stream, "close", None)
                if callable(close):
                    close()

            content = "".join(chunks).strip()
            if owner_result is None:
                if not content:
                    raise LLMProviderError(
                        "LLM_PROVIDER_EMPTY_RESPONSE",
                        "The language model provider returned no text.",
                        retryable=False,
                    )
                owner_result = LLMResult(
                    content=content,
                    provider=self.llm_provider.provider_name,
                    model=self.llm_provider.model_name,
                )
            elif not chunks and owner_result.content:
                content = owner_result.content
                yield TurnStreamSignal(
                    kind="delta",
                    payload={
                        "content": content,
                        "chunk_index": 0,
                        "replayed": False,
                    },
                )
            else:
                content = owner_result.content or content

        except LLMProviderError as exc:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code=exc.code,
                error_message=exc.safe_message,
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            log_execution_event(
                "execution_terminal_error",
                failed,
                error_code=failed.error_code,
                provider=self.llm_provider.provider_name,
                retryable=exc.retryable,
            )
            yield TurnStreamSignal(
                kind="terminal",
                payload={"replayed": False},
                response=self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
            )
            return
        except Exception:
            terminal_message = self._assistant_message(
                context,
                "",
                status="error",
                error_code="PROVIDER_EXECUTION_FAILED",
                error_message="The provider execution failed.",
            )
            failed = self.repository.fail_execution(
                execution,
                user_message,
                terminal_message,
            )
            log_execution_event(
                "execution_terminal_error",
                failed,
                error_code=failed.error_code,
                provider=self.llm_provider.provider_name,
            )
            yield TurnStreamSignal(
                kind="terminal",
                payload={"replayed": False},
                response=self.response_from_execution(
                    failed,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
            )
            return

        execution = self.heartbeat_turn(execution)
        current = self.repository.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        if current is not None and current.status == "cancelled":
            yield TurnStreamSignal(
                kind="terminal",
                payload={"replayed": False},
                response=self.response_from_execution(
                    current,
                    latency_ms=int(
                        (perf_counter() - started) * 1000
                    ),
                ),
            )
            return

        assistant_message = self._assistant_message(
            context,
            content,
            status="success",
        )
        try:
            completed = self.repository.complete_execution(
                execution,
                user_message,
                assistant_message,
            )
        except Exception as exc:
            current = self.repository.get_execution(
                execution.tenant_id,
                execution.request_id,
            )
            if current is not None and current.status == "cancelled":
                yield TurnStreamSignal(
                    kind="terminal",
                    payload={"replayed": False},
                    response=self.response_from_execution(
                        current,
                        latency_ms=int(
                            (perf_counter() - started) * 1000
                        ),
                    ),
                )
                return
            try:
                self.repository.abort_execution(
                    execution.tenant_id,
                    execution.request_id,
                    error_code="TURN_PERSISTENCE_FAILED",
                    error_message=(
                        "The turn could not be persisted atomically."
                    ),
                )
            except Exception:
                pass
            raise ServiceUnavailableError(
                "TURN_PERSISTENCE_FAILED",
                "The turn could not be persisted atomically.",
            ) from exc

        contribution_tuple = tuple(contributions)
        token_usage = self._aggregate_token_usage(
            contribution_tuple,
            owner_result,
        )
        execution_trace = self._execution_trace(
            context,
            contribution_tuple,
            owner_result,
        )
        log_execution_event(
            "execution_terminal_success",
            completed,
            provider=(
                owner_result.provider
                if owner_result is not None
                else self.llm_provider.provider_name
            ),
            model=(
                owner_result.model
                if owner_result is not None
                else self.llm_provider.model_name
            ),
            token_usage=token_usage,
            contributor_agents=[
                item.agent_id for item in contribution_tuple
            ],
        )
        response = self.response_from_execution(
            completed,
            latency_ms=int((perf_counter() - started) * 1000),
        )
        updates: dict[str, object] = {
            "execution_trace": execution_trace,
        }
        if token_usage is not None:
            updates["token_usage"] = token_usage
        response = response.model_copy(update=updates)
        yield TurnStreamSignal(
            kind="terminal",
            payload={"replayed": False},
            response=response,
        )

    def cancel_execution(
        self,
        principal: PrincipalContext,
        request_id: str,
        *,
        reason: str,
    ) -> ResponseEnvelope:
        execution = self.repository.get_execution(
            principal.tenant_id,
            request_id,
        )
        if execution is None:
            raise NotFoundError(
                "EXECUTION_NOT_FOUND",
                "Execution not found.",
            )
        if execution.status != "running":
            return self.response_from_execution(execution)

        context = AgentTurnContext(
            request_id=execution.request_id,
            execution_id=execution.execution_id,
            thread_id=execution.thread_id,
            tenant_id=execution.tenant_id,
            user_id=execution.user_id,
            requested_agent=execution.requested_agent,
            resolved_agent=execution.resolved_agent,
            turn_owner=execution.turn_owner,
            display_agent=execution.display_name,
            route_family=execution.route_family,
        )
        cancellation_message = self._assistant_message(
            context,
            "Execution cancelled.",
            status="cancelled",
            error_code="EXECUTION_CANCELLED",
            error_message=reason,
        )
        cancelled = self.repository.cancel_execution(
            execution,
            cancellation_message,
        )
        log_execution_event(
            "execution_terminal_cancelled",
            cancelled,
            cancelled_by=principal.user_id,
        )
        return self.response_from_execution(cancelled)

    def record_recovery_decision(
        self,
        principal: PrincipalContext,
        request_id: str,
        payload: RecoveryDecisionCreate,
    ) -> RecoveryDecisionRecord:
        execution = self.repository.get_execution(
            principal.tenant_id,
            request_id,
        )
        if execution is None:
            raise NotFoundError(
                "EXECUTION_NOT_FOUND",
                "Execution not found.",
            )
        decision = RecoveryDecisionRecord(
            tenant_id=principal.tenant_id,
            decision_id=new_id("recovery_decision"),
            request_id=request_id,
            execution_id=execution.execution_id,
            actor_id=principal.user_id,
            decision=payload.decision,
            reason=payload.reason,
        )
        recorded = self.repository.record_recovery_decision(
            decision,
        )
        log_execution_event(
            "recovery_decision_recorded",
            execution,
            decision=recorded.decision,
            decision_id=recorded.decision_id,
            automatic_recovery=False,
        )
        return recorded

    def complete_chat(
        self,
        principal: PrincipalContext,
        request: ChatRequest,
    ) -> ResponseEnvelope:
        started = perf_counter()
        context = self.prepare_turn(principal, request)
        context, execution, created = self.reserve_turn(
            context,
            request,
        )
        response, _ = self.execute_reserved_turn(
            context,
            execution,
            request,
            created=created,
            started=started,
        )
        return response
