from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from datetime import timedelta, timezone
from time import perf_counter

from orkio_platform.application.catalog import resolve_agent
from orkio_platform.application.streaming import TurnStreamSignal
from orkio_platform.knowledge.snapshot import (
    KNOWLEDGE_SNAPSHOT_VERSION,
)
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
    contribution_retry_prompt_for_agent,
    roundtable_owner_prompt,
    roundtable_owner_retry_prompt,
    synthesis_prompt_for_agent,
    system_prompt_for_agent,
)
from orkio_platform.domain.errors import (
    ConflictError,
    DomainError,
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
from orkio_platform.integrations.repository_audit import (
    RepositoryAuditProvider,
)
from orkio_platform.observability.execution import log_execution_event
from orkio_platform.orchestration.contracts import AgentContribution
from orkio_platform.orchestration.task_decomposition import (
    OwnerContract,
    TaskSlice,
    decompose_user_request,
)
from orkio_platform.orchestration.router import build_orchestration_plan
from orkio_platform.orchestration.output_normalization import (
    AgentOutputAssessment,
    assess_agent_output,
    assess_owner_output,
)


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
        multiagent_contribution_max_chars: int = 4_000,
        multiagent_contribution_max_output_tokens: int = 900,
        multiagent_owner_max_output_tokens: int = 1_200,
        multiagent_contribution_latency_budget_ms: int = 15_000,
        multiagent_turn_latency_budget_ms: int = 25_000,
        multiagent_history_messages: int = 4,
        multiagent_max_context_chars: int = 20_000,
        multiagent_turn_max_total_tokens: int = 7_000,
        repository_audit_provider: RepositoryAuditProvider | None = None,
        knowledge_snapshot_version: str = KNOWLEDGE_SNAPSHOT_VERSION,
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
        if multiagent_contribution_max_chars < 500:
            raise ValueError("MULTIAGENT_CONTRIBUTION_MAX_CHARS_INVALID")
        if multiagent_contribution_max_output_tokens < 64:
            raise ValueError(
                "MULTIAGENT_CONTRIBUTION_OUTPUT_BUDGET_INVALID"
            )
        if multiagent_owner_max_output_tokens < 64:
            raise ValueError("MULTIAGENT_OWNER_OUTPUT_BUDGET_INVALID")
        if multiagent_contribution_latency_budget_ms < 100:
            raise ValueError(
                "MULTIAGENT_CONTRIBUTION_LATENCY_BUDGET_INVALID"
            )
        if multiagent_turn_latency_budget_ms < 100:
            raise ValueError("MULTIAGENT_TURN_LATENCY_BUDGET_INVALID")
        if multiagent_history_messages < 0:
            raise ValueError("MULTIAGENT_HISTORY_MESSAGES_INVALID")
        if multiagent_max_context_chars < 1_000:
            raise ValueError("MULTIAGENT_MAX_CONTEXT_CHARS_INVALID")
        if multiagent_turn_max_total_tokens < 256:
            raise ValueError("MULTIAGENT_TURN_TOKEN_BUDGET_INVALID")
        if not knowledge_snapshot_version.strip():
            raise ValueError("KNOWLEDGE_SNAPSHOT_VERSION_REQUIRED")
        self.multiagent_contribution_max_chars = (
            multiagent_contribution_max_chars
        )
        self.multiagent_contribution_max_output_tokens = (
            multiagent_contribution_max_output_tokens
        )
        self.multiagent_owner_max_output_tokens = (
            multiagent_owner_max_output_tokens
        )
        self.multiagent_contribution_latency_budget_ms = (
            multiagent_contribution_latency_budget_ms
        )
        self.multiagent_turn_latency_budget_ms = (
            multiagent_turn_latency_budget_ms
        )
        self.multiagent_history_messages = multiagent_history_messages
        self.multiagent_max_context_chars = multiagent_max_context_chars
        self.multiagent_turn_max_total_tokens = (
            multiagent_turn_max_total_tokens
        )
        self.repository_audit_provider = repository_audit_provider
        self.knowledge_snapshot_version = (
            knowledge_snapshot_version.strip()
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

    def rename_thread(
        self,
        principal: PrincipalContext,
        thread_id: str,
        title: str,
    ) -> ThreadRecord:
        normalized = " ".join(title.split())
        if not normalized:
            raise DomainError(
                "THREAD_TITLE_REQUIRED",
                "Thread title is required.",
                status_code=400,
            )
        return self.repository.update_thread_title(
            principal.tenant_id,
            thread_id,
            normalized,
        )

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
            interaction_mode=request.interaction_mode,
        )
        owner = resolve_agent(plan.owner_agent)
        return AgentTurnContext(
            request_id=request.request_id or new_id("request"),
            execution_id=new_id("execution"),
            thread_id=request.thread_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            principal_role=principal.role,
            requested_agent=plan.requested_agent,
            resolved_agent=owner.agent_id,
            turn_owner=owner.agent_id,
            display_agent=owner.display_name,
            route_family=plan.route_family,
            interaction_mode=plan.interaction_mode,
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
            "interaction_mode": context.interaction_mode,
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
        *,
        history_messages_limit: int | None = None,
        max_context_chars: int | None = None,
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
        history_limit = (
            self.llm_history_messages
            if history_messages_limit is None
            else history_messages_limit
        )
        if history_limit == 0:
            eligible = []
        else:
            eligible = eligible[-history_limit:]
        context_char_limit = (
            self.llm_max_context_chars
            if max_context_chars is None
            else max_context_chars
        )

        current = LLMMessage(
            role="user",
            content=request.content,
        )
        selected: list[LLMMessage] = [current]
        used_chars = len(current.content)

        for message in reversed(eligible):
            message_chars = len(message.content)
            if used_chars + message_chars > context_char_limit:
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
        current_only: bool = False,
        current_content: str | None = None,
        max_output_tokens: int | None = None,
        history_messages_limit: int | None = None,
        max_context_chars: int | None = None,
    ) -> LLMCompletionRequest:
        agent = resolve_agent(agent_id)
        effective_content = current_content or request.content
        effective_request = request.model_copy(
            update={"content": effective_content},
        )
        messages = (
            (
                LLMMessage(
                    role="user",
                    content=effective_content,
                ),
            )
            if current_only
            else self._history_messages(
                context,
                effective_request,
                history_messages_limit=history_messages_limit,
                max_context_chars=max_context_chars,
            )
        )
        return LLMCompletionRequest(
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            thread_id=context.thread_id,
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            system_prompt=system_prompt,
            messages=messages,
            max_output_tokens=max_output_tokens,
        )


    def _contribution_request(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributor_id: str,
        *,
        retry_reason: str | None = None,
        task_slice: TaskSlice | None = None,
    ) -> LLMCompletionRequest:
        contributor = resolve_agent(contributor_id)
        selected_task = task_slice or decompose_user_request(
            request.content,
        ).for_agent(contributor_id)
        system_prompt = (
            contribution_retry_prompt_for_agent(
                contributor,
                retry_reason,
            )
            if retry_reason
            else contribution_prompt_for_agent(contributor)
        )
        return self._llm_request_for_agent(
            context,
            request,
            agent_id=contributor.agent_id,
            system_prompt=system_prompt,
            current_only=True,
            current_content=selected_task.user_message,
            max_output_tokens=(
                self.multiagent_contribution_max_output_tokens
            ),
            history_messages_limit=0,
            max_context_chars=self.multiagent_max_context_chars,
        )


    def _repository_audit_prompt_block(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> str:
        provider = self.repository_audit_provider
        if provider is None:
            return ""
        evidence = provider.maybe_collect(
            context,
            request.content,
        )
        if evidence is None:
            return ""
        return evidence.prompt_block

    def _owner_request(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributions: tuple[AgentContribution, ...],
        *,
        retry_reason: str | None = None,
    ) -> LLMCompletionRequest:
        owner = resolve_agent(context.turn_owner)
        decomposition = decompose_user_request(request.content)
        owner_slice = decomposition.for_agent(context.turn_owner)
        owner_contract = decomposition.owner_contract

        if context.interaction_mode == "roundtable":
            system_prompt = (
                roundtable_owner_retry_prompt(
                    owner,
                    contributions,
                    retry_reason,
                    owner_contract,
                )
                if retry_reason
                else roundtable_owner_prompt(
                    owner,
                    contributions,
                    owner_contract,
                )
            )
        else:
            system_prompt = synthesis_prompt_for_agent(
                owner,
                contributions,
            )

        repository_prompt_block = self._repository_audit_prompt_block(
            context,
            request,
        )
        if repository_prompt_block:
            system_prompt = system_prompt + repository_prompt_block

        multiagent_request = context.interaction_mode != "single"
        return self._llm_request_for_agent(
            context,
            request,
            agent_id=owner.agent_id,
            system_prompt=system_prompt,
            current_only=multiagent_request,
            current_content=(
                owner_slice.user_message
                if multiagent_request
                else request.content
            ),
            max_output_tokens=(
                self.multiagent_owner_max_output_tokens
                if multiagent_request
                else None
            ),
            history_messages_limit=0 if multiagent_request else None,
            max_context_chars=(
                self.multiagent_max_context_chars
                if multiagent_request
                else None
            ),
        )

    @staticmethod
    def _summed_result_tokens(
        results: list[LLMResult],
        attribute: str,
    ) -> int | None:
        values = [
            getattr(result, attribute)
            for result in results
            if getattr(result, attribute) is not None
        ]
        return sum(values) if values else None

    def _contribution_from_attempts(
        self,
        agent_id: str,
        results: list[LLMResult],
        assessment: AgentOutputAssessment,
        task_slice: TaskSlice,
        *,
        retry_count: int,
        latency_ms: int,
    ) -> AgentContribution:
        agent = resolve_agent(agent_id)
        final = results[-1]
        output_tokens = self._summed_result_tokens(
            results,
            "output_tokens",
        )
        budget_exceeded = (
            latency_ms
            > self.multiagent_contribution_latency_budget_ms
            or any(
                result.output_tokens is not None
                and result.output_tokens
                > self.multiagent_contribution_max_output_tokens
                for result in results
            )
        )
        return AgentContribution(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            content=assessment.content,
            provider=final.provider,
            model=final.model,
            response_id=final.response_id,
            input_tokens=self._summed_result_tokens(
                results,
                "input_tokens",
            ),
            output_tokens=output_tokens,
            total_tokens=self._summed_result_tokens(
                results,
                "total_tokens",
            ),
            status=assessment.status,
            status_reason=assessment.reason,
            retry_count=retry_count,
            latency_ms=latency_ms,
            output_normalized=assessment.normalized,
            budget_exceeded=budget_exceeded,
            contract_version=assessment.contract_version,
            assigned_task=task_slice.assigned_task,
            task_slice_version=task_slice.version,
            explicit_assignment=task_slice.explicit_assignment,
        )


    def _failed_contribution(
        self,
        agent_id: str,
        *,
        reason: str,
        latency_ms: int,
        task_slice: TaskSlice | None = None,
        retry_count: int = 0,
    ) -> AgentContribution:
        agent = resolve_agent(agent_id)
        return AgentContribution(
            agent_id=agent.agent_id,
            display_name=agent.display_name,
            content="",
            provider=self.llm_provider.provider_name,
            model=self.llm_provider.model_name,
            status="failed",
            status_reason=reason,
            retry_count=retry_count,
            latency_ms=latency_ms,
            budget_exceeded=(
                latency_ms
                > self.multiagent_contribution_latency_budget_ms
            ),
            assigned_task=(
                task_slice.assigned_task
                if task_slice is not None
                else None
            ),
            task_slice_version=(
                task_slice.version
                if task_slice is not None
                else "task_slice_v1"
            ),
            explicit_assignment=(
                task_slice.explicit_assignment
                if task_slice is not None
                else False
            ),
        )


    def _complete_contribution(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributor_id: str,
    ) -> AgentContribution:
        started = perf_counter()
        results: list[LLMResult] = []
        retry_count = 0
        task_slice = decompose_user_request(
            request.content,
        ).for_agent(contributor_id)
        try:
            first = self.llm_provider.complete(
                self._contribution_request(
                    context,
                    request,
                    contributor_id,
                    task_slice=task_slice,
                )
            )
            results.append(first)
            assessment = assess_agent_output(
                first.content,
                contributor_id,
                max_chars=self.multiagent_contribution_max_chars,
            )

            if assessment.retryable_contract_failure:
                retry_count = 1
                second = self.llm_provider.complete(
                    self._contribution_request(
                        context,
                        request,
                        contributor_id,
                        retry_reason=(
                            assessment.reason
                            or assessment.status
                        ),
                        task_slice=task_slice,
                    )
                )
                results.append(second)
                assessment = assess_agent_output(
                    second.content,
                    contributor_id,
                    max_chars=(
                        self.multiagent_contribution_max_chars
                    ),
                )
        except LLMProviderError as exc:
            return self._failed_contribution(
                contributor_id,
                reason=exc.code,
                retry_count=retry_count,
                task_slice=task_slice,
                latency_ms=int(
                    (perf_counter() - started) * 1000
                ),
            )
        except Exception:
            return self._failed_contribution(
                contributor_id,
                reason="PROVIDER_EXECUTION_FAILED",
                retry_count=retry_count,
                task_slice=task_slice,
                latency_ms=int(
                    (perf_counter() - started) * 1000
                ),
            )

        return self._contribution_from_attempts(
            contributor_id,
            results,
            assessment,
            task_slice,
            retry_count=retry_count,
            latency_ms=int((perf_counter() - started) * 1000),
        )


    def generate_contributions(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[AgentContribution, ...]:
        return tuple(
            self._complete_contribution(
                context,
                request,
                contributor_id,
            )
            for contributor_id in context.contributing_agents
        )

    def _owner_result_from_attempts(
        self,
        context: AgentTurnContext,
        results: list[LLMResult],
        assessment: AgentOutputAssessment | None,
        *,
        owner_contract: OwnerContract,
        retry_count: int,
        latency_ms: int,
    ) -> tuple[LLMResult, dict[str, object]]:
        final = results[-1]
        partial = (
            assessment is not None
            and assessment.status != "success"
        )
        if assessment is None:
            content = final.content
            status = "success"
            reason = None
            normalized = False
            contract_version = "owner_synthesis_v1"
        elif partial:
            content = (
                "A síntese de Orkio foi bloqueada porque não cumpriu "
                "o contrato adaptativo. As contribuições validadas "
                "foram preservadas."
            )
            status = "partial"
            reason = assessment.reason or assessment.status
            normalized = True
            contract_version = assessment.contract_version
        else:
            content = assessment.content
            status = "success"
            reason = None
            normalized = assessment.normalized
            contract_version = assessment.contract_version

        result = LLMResult(
            content=content,
            provider=final.provider,
            model=final.model,
            response_id=final.response_id,
            input_tokens=self._summed_result_tokens(
                results,
                "input_tokens",
            ),
            output_tokens=self._summed_result_tokens(
                results,
                "output_tokens",
            ),
            total_tokens=self._summed_result_tokens(
                results,
                "total_tokens",
            ),
        )
        metadata: dict[str, object] = {
            "status": status,
            "reason": reason,
            "retry_count": retry_count,
            "latency_ms": latency_ms,
            "output_normalized": normalized,
            "contract_version": contract_version,
            "owner_contract": owner_contract,
            "task_slice_version": "task_slice_v1",
            "contributors_preserved": partial,
            "retry_scope": "owner_only",
            "budget_exceeded": (
                latency_ms > self.multiagent_turn_latency_budget_ms
                or any(
                    item.output_tokens is not None
                    and item.output_tokens
                    > self.multiagent_owner_max_output_tokens
                    for item in results
                )
            ),
        }
        return result, metadata

    def _complete_owner(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
        contributions: tuple[AgentContribution, ...],
    ) -> tuple[LLMResult, dict[str, object]]:
        started = perf_counter()
        decomposition = decompose_user_request(request.content)
        owner_contract = decomposition.owner_contract
        results: list[LLMResult] = [
            self.llm_provider.complete(
                self._owner_request(
                    context,
                    request,
                    contributions,
                )
            )
        ]
        assessment: AgentOutputAssessment | None = None
        retry_count = 0

        if context.interaction_mode == "roundtable":
            assessment = assess_owner_output(
                results[-1].content,
                context.turn_owner,
                owner_contract=owner_contract,
                max_chars=self.multiagent_contribution_max_chars,
            )
            if assessment.retryable_contract_failure:
                retry_count = 1
                results.append(
                    self.llm_provider.complete(
                        self._owner_request(
                            context,
                            request,
                            contributions,
                            retry_reason=(
                                assessment.reason
                                or assessment.status
                            ),
                        )
                    )
                )
                assessment = assess_owner_output(
                    results[-1].content,
                    context.turn_owner,
                    owner_contract=owner_contract,
                    max_chars=(
                        self.multiagent_contribution_max_chars
                    ),
                )

        return self._owner_result_from_attempts(
            context,
            results,
            assessment,
            owner_contract=owner_contract,
            retry_count=retry_count,
            latency_ms=int((perf_counter() - started) * 1000),
        )


    def generate_content(
        self,
        context: AgentTurnContext,
        request: ChatRequest,
    ) -> tuple[
        LLMResult,
        tuple[AgentContribution, ...],
        dict[str, object],
    ]:
        contributions = self.generate_contributions(
            context,
            request,
        )
        result, owner_contract = self._complete_owner(
            context,
            request,
            contributions,
        )
        return result, contributions, owner_contract

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
    def _contribution_payloads(
        contributions: tuple[AgentContribution, ...],
    ) -> list[dict[str, object]]:
        return [
            {
                "agent_id": item.agent_id,
                "display_name": item.display_name,
                "role": "contributor",
                "status": item.status,
                "status_reason": item.status_reason,
                "content": item.content,
                "provider": item.provider,
                "model": item.model,
                "token_usage": item.token_usage(),
                "retry_count": item.retry_count,
                "latency_ms": item.latency_ms,
                "output_normalized": item.output_normalized,
                "budget_exceeded": item.budget_exceeded,
                "contract_version": item.contract_version,
                "assigned_task": item.assigned_task,
                "task_slice_version": item.task_slice_version,
                "explicit_assignment": item.explicit_assignment,
            }
            for item in contributions
        ]

    @staticmethod
    def _interaction_mode_from_route(route_family: str) -> str:
        if "roundtable" in route_family:
            return "roundtable"
        if (
            "synthesis" in route_family
            or route_family == "team_multiagent"
        ):
            return "team_synthesis"
        return "single"

    @staticmethod
    def _public_contribution_content(
        contribution: AgentContribution,
    ) -> str:
        if contribution.status == "success":
            return contribution.content.strip()
        if contribution.status == "refused":
            return (
                "Contribuição recusada pelo agente. "
                "A execução não foi marcada como sucesso."
            )
        if contribution.status == "contract_violation":
            return (
                "Contribuição bloqueada pelo contrato de autoria "
                f"({contribution.status_reason or 'violação não especificada'})."
            )
        return (
            "Contribuição indisponível por falha controlada "
            f"({contribution.status_reason or 'falha não especificada'})."
        )

    @staticmethod
    def _final_content(
        context: AgentTurnContext,
        contributions: tuple[AgentContribution, ...],
        owner_result: LLMResult,
    ) -> str:
        if context.interaction_mode != "roundtable":
            return owner_result.content

        blocks = [
            (
                f"### {item.display_name}\n"
                f"{PlatformService._public_contribution_content(item)}"
            )
            for item in contributions
        ]
        owner_name = resolve_agent(context.turn_owner).display_name
        if owner_result.content.strip():
            blocks.append(
                f"### {owner_name}\n{owner_result.content.strip()}"
            )
        return "\n\n".join(blocks).strip()

    def _execution_trace(
        self,
        context: AgentTurnContext,
        contributions: tuple[AgentContribution, ...],
        owner_result: LLMResult | None,
        owner_contract: dict[str, object] | None = None,
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
                    "status": item.status,
                    "status_reason": item.status_reason,
                    "trace_kind": context.trace_kind,
                    "provider": item.provider,
                    "model": item.model,
                    "token_usage": item.token_usage(),
                    "retry_count": item.retry_count,
                    "latency_ms": item.latency_ms,
                    "output_normalized": item.output_normalized,
                    "budget_exceeded": item.budget_exceeded,
                    "contract_version": item.contract_version,
                    "assigned_task": item.assigned_task,
                    "task_slice_version": item.task_slice_version,
                    "explicit_assignment": item.explicit_assignment,
                }
            )
        trace.append(
            {
                "node_id": f"{context.execution_id}:owner",
                "agent_id": context.turn_owner,
                "role": "owner",
                "status": (
                    owner_contract.get("status", "success")
                    if owner_contract is not None
                    else (
                        "success"
                        if owner_result is not None
                        else "unknown"
                    )
                ),
                "status_reason": (
                    owner_contract.get("reason")
                    if owner_contract is not None
                    else None
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
                "retry_count": (
                    owner_contract.get("retry_count", 0)
                    if owner_contract is not None
                    else 0
                ),
                "latency_ms": (
                    owner_contract.get("latency_ms")
                    if owner_contract is not None
                    else None
                ),
                "output_normalized": (
                    owner_contract.get("output_normalized", False)
                    if owner_contract is not None
                    else False
                ),
                "budget_exceeded": (
                    owner_contract.get("budget_exceeded", False)
                    if owner_contract is not None
                    else False
                ),
                "contract_version": (
                    owner_contract.get(
                        "contract_version",
                        "owner_synthesis_v1",
                    )
                    if owner_contract is not None
                    else "owner_synthesis_v1"
                ),
            }
        )
        return trace

    def _budget_metadata(
        self,
        *,
        latency_ms: int | None,
        token_usage: dict[str, int] | None = None,
    ) -> dict[str, object]:
        return {
            "contribution_max_output_tokens": (
                self.multiagent_contribution_max_output_tokens
            ),
            "owner_max_output_tokens": (
                self.multiagent_owner_max_output_tokens
            ),
            "contribution_latency_budget_ms": (
                self.multiagent_contribution_latency_budget_ms
            ),
            "turn_latency_budget_ms": (
                self.multiagent_turn_latency_budget_ms
            ),
            "history_messages": self.multiagent_history_messages,
            "max_context_chars": self.multiagent_max_context_chars,
            "turn_max_total_tokens": (
                self.multiagent_turn_max_total_tokens
            ),
            "observed_total_tokens": (
                token_usage.get("total_tokens")
                if token_usage is not None
                else None
            ),
            "turn_token_budget_exceeded": (
                token_usage is not None
                and token_usage.get("total_tokens", 0)
                > self.multiagent_turn_max_total_tokens
            ),
            "turn_latency_exceeded": (
                latency_ms is not None
                and latency_ms > self.multiagent_turn_latency_budget_ms
            ),
        }

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
        if execution.status in {"error", "partial"}:
            error = {
                "code": (
                    execution.error_code
                    or (
                        "EXECUTION_PARTIAL"
                        if execution.status == "partial"
                        else "EXECUTION_FAILED"
                    )
                ),
                "message": (
                    execution.error_message
                    or (
                        "A execução terminou parcialmente."
                        if execution.status == "partial"
                        else "The execution ended with an error."
                    )
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
            interaction_mode=self._interaction_mode_from_route(
                execution.route_family
            ),
            content=content,
            status=execution.status,
            error=error,
            budget=self._budget_metadata(latency_ms=latency_ms),
            knowledge_snapshot_version=self.knowledge_snapshot_version,
            transport="http_json",
            terminal_source="envelope",
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
        owner_contract: dict[str, object] | None = None
        try:
            (
                provider_result,
                contributions,
                owner_contract,
            ) = self.generate_content(
                context,
                request,
            )
            content = self._final_content(
                context,
                contributions,
                provider_result,
            )
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

        partial_owner = (
            owner_contract is not None
            and owner_contract.get("status") == "partial"
        )
        assistant_message = self._assistant_message(
            context,
            content,
            status="partial" if partial_owner else "success",
            error_code=(
                "OWNER_CONTRACT_PARTIAL"
                if partial_owner
                else None
            ),
            error_message=(
                "A síntese final foi bloqueada; as contribuições "
                "validadas foram preservadas."
                if partial_owner
                else None
            ),
        )
        try:
            completed = (
                self.repository.partial_execution(
                    execution,
                    user_message,
                    assistant_message,
                )
                if partial_owner
                else self.repository.complete_execution(
                    execution,
                    user_message,
                    assistant_message,
                )
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
            owner_contract,
        )
        log_execution_event(
            (
                "execution_terminal_partial"
                if partial_owner
                else "execution_terminal_success"
            ),
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
            "interaction_mode": context.interaction_mode,
            "contributions": self._contribution_payloads(
                contributions
            ),
            "owner_contract": owner_contract,
            "knowledge_snapshot_version": (
                self.knowledge_snapshot_version
            ),
            "budget": self._budget_metadata(
                latency_ms=response.latency_ms,
                token_usage=token_usage,
            ),
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
        owner_contract: dict[str, object] | None = None
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
                        "display_name": resolve_agent(
                            contributor_id
                        ).display_name,
                        "role": "contributor",
                        "trace_kind": context.trace_kind,
                        "interaction_mode": context.interaction_mode,
                    },
                )
                contribution = self._complete_contribution(
                    context,
                    request,
                    contributor_id,
                )
                contributions.append(contribution)
                yield TurnStreamSignal(
                    kind="execution",
                    payload={
                        "phase": "node_completed",
                        "node_id": node_id,
                        "agent_id": contributor_id,
                        "display_name": contribution.display_name,
                        "role": "contributor",
                        "trace_kind": context.trace_kind,
                        "interaction_mode": context.interaction_mode,
                        "status": contribution.status,
                        "status_reason": contribution.status_reason,
                        "content": contribution.content,
                        "provider": contribution.provider,
                        "model": contribution.model,
                        "token_usage": contribution.token_usage(),
                        "retry_count": contribution.retry_count,
                        "latency_ms": contribution.latency_ms,
                        "output_normalized": (
                            contribution.output_normalized
                        ),
                        "budget_exceeded": (
                            contribution.budget_exceeded
                        ),
                        "contract_version": (
                            contribution.contract_version
                        ),
                        "assigned_task": (
                            contribution.assigned_task
                        ),
                        "task_slice_version": (
                            contribution.task_slice_version
                        ),
                        "explicit_assignment": (
                            contribution.explicit_assignment
                        ),
                    },
                )

            owner_started = perf_counter()
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
                        if context.interaction_mode != "roundtable":
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

            streamed_owner_content = "".join(chunks).strip()
            if owner_result is None:
                if not streamed_owner_content:
                    raise LLMProviderError(
                        "LLM_PROVIDER_EMPTY_RESPONSE",
                        "The language model provider returned no text.",
                        retryable=False,
                    )
                owner_result = LLMResult(
                    content=streamed_owner_content,
                    provider=self.llm_provider.provider_name,
                    model=self.llm_provider.model_name,
                )
            elif not chunks and owner_result.content:
                streamed_owner_content = owner_result.content
                if context.interaction_mode != "roundtable":
                    yield TurnStreamSignal(
                        kind="delta",
                        payload={
                            "content": streamed_owner_content,
                            "chunk_index": 0,
                            "replayed": False,
                        },
                    )
            elif not owner_result.content:
                owner_result = LLMResult(
                    content=streamed_owner_content,
                    provider=owner_result.provider,
                    model=owner_result.model,
                    response_id=owner_result.response_id,
                    input_tokens=owner_result.input_tokens,
                    output_tokens=owner_result.output_tokens,
                    total_tokens=owner_result.total_tokens,
                )

            if context.interaction_mode == "roundtable":
                active_owner_contract = decompose_user_request(
                    request.content,
                ).owner_contract
                owner_results = [owner_result]
                assessment = assess_owner_output(
                    owner_result.content,
                    context.turn_owner,
                    owner_contract=active_owner_contract,
                    max_chars=self.multiagent_contribution_max_chars,
                )
                owner_retry_count = 0
                if assessment.retryable_contract_failure:
                    owner_retry_count = 1
                    retry_result = self.llm_provider.complete(
                        self._owner_request(
                            context,
                            request,
                            tuple(contributions),
                            retry_reason=(
                                assessment.reason
                                or assessment.status
                            ),
                        )
                    )
                    owner_results.append(retry_result)
                    assessment = assess_owner_output(
                        retry_result.content,
                        context.turn_owner,
                        owner_contract=active_owner_contract,
                        max_chars=(
                            self.multiagent_contribution_max_chars
                        ),
                    )

                owner_result, owner_contract = (
                    self._owner_result_from_attempts(
                        context,
                        owner_results,
                        assessment,
                        owner_contract=active_owner_contract,
                        retry_count=owner_retry_count,
                        latency_ms=int(
                            (perf_counter() - owner_started) * 1000
                        ),
                    )
                )
                if owner_result.content:
                    yield TurnStreamSignal(
                        kind="delta",
                        payload={
                            "content": owner_result.content,
                            "chunk_index": 0,
                            "replayed": False,
                            "normalized": (
                                owner_contract.get(
                                    "output_normalized",
                                    False,
                                )
                            ),
                            "owner_status": owner_contract.get(
                                "status",
                                "success",
                            ),
                        },
                    )
            else:
                owner_contract = {
                    "status": "success",
                    "reason": None,
                    "retry_count": 0,
                    "latency_ms": int(
                        (perf_counter() - owner_started) * 1000
                    ),
                    "output_normalized": False,
                    "contract_version": "owner_synthesis_v1",
                    "owner_contract": "factual_summary_v1",
                    "task_slice_version": "task_slice_v1",
                    "contributors_preserved": False,
                    "retry_scope": "owner_only",
                    "budget_exceeded": False,
                }

            content = self._final_content(
                context,
                tuple(contributions),
                owner_result,
            )

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

        partial_owner = (
            owner_contract is not None
            and owner_contract.get("status") == "partial"
        )
        assistant_message = self._assistant_message(
            context,
            content,
            status="partial" if partial_owner else "success",
            error_code=(
                "OWNER_CONTRACT_PARTIAL"
                if partial_owner
                else None
            ),
            error_message=(
                "A síntese final foi bloqueada; as contribuições "
                "validadas foram preservadas."
                if partial_owner
                else None
            ),
        )
        try:
            completed = (
                self.repository.partial_execution(
                    execution,
                    user_message,
                    assistant_message,
                )
                if partial_owner
                else self.repository.complete_execution(
                    execution,
                    user_message,
                    assistant_message,
                )
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
            owner_contract,
        )
        log_execution_event(
            (
                "execution_terminal_partial"
                if partial_owner
                else "execution_terminal_success"
            ),
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
            output_normalization=(
                "speaker_contract_v4"
                if context.interaction_mode == "roundtable"
                else "not_required"
            ),
        )
        response = self.response_from_execution(
            completed,
            latency_ms=int((perf_counter() - started) * 1000),
        )
        updates: dict[str, object] = {
            "execution_trace": execution_trace,
            "interaction_mode": context.interaction_mode,
            "contributions": self._contribution_payloads(
                contribution_tuple
            ),
            "owner_contract": owner_contract,
            "knowledge_snapshot_version": (
                self.knowledge_snapshot_version
            ),
            "budget": self._budget_metadata(
                latency_ms=response.latency_ms,
                token_usage=token_usage,
            ),
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
