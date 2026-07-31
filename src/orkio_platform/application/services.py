from __future__ import annotations

import hashlib
import json
from datetime import timedelta, timezone
from time import perf_counter

from orkio_platform.application.catalog import resolve_agent
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


class PlatformService:
    def __init__(
        self,
        repository: RepositoryProtocol,
        *,
        execution_lease_seconds: int = 60,
        execution_stale_after_seconds: int = 300,
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
        agent = resolve_agent(request.requested_agent)
        return AgentTurnContext(
            request_id=request.request_id or new_id("request"),
            execution_id=new_id("execution"),
            thread_id=request.thread_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            requested_agent=request.requested_agent or agent.agent_id,
            resolved_agent=agent.agent_id,
            turn_owner=agent.agent_id,
            display_agent=agent.display_name,
            route_family=(
                "explicit_agent"
                if request.requested_agent
                else "default_orchestrator"
            ),
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

    def deterministic_content(
        self,
        context: AgentTurnContext,
    ) -> str:
        return (
            f"[{context.display_agent}] Recebi sua mensagem no tenant "
            f"{context.tenant_id}. RC1 Premium Hardening R0.3 opera "
            "com provider determinístico local."
        )

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

        try:
            content = self.deterministic_content(context)
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

        log_execution_event(
            "execution_terminal_success",
            completed,
        )
        return (
            self.response_from_execution(
                completed,
                latency_ms=int((perf_counter() - started) * 1000),
            ),
            False,
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
