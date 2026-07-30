from __future__ import annotations

from time import perf_counter

from orkio_platform.application.catalog import resolve_agent
from orkio_platform.domain.models import (
    AgentTurnContext,
    ChatRequest,
    MessageRecord,
    PrincipalContext,
    ResponseEnvelope,
    ThreadRecord,
    new_id,
)
from orkio_platform.infrastructure.repositories import InMemoryRepository


class PlatformService:
    def __init__(self, repository: InMemoryRepository) -> None:
        self.repository = repository

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

    def list_threads(self, principal: PrincipalContext) -> list[ThreadRecord]:
        return self.repository.list_threads(principal.tenant_id)

    def list_messages(
        self,
        principal: PrincipalContext,
        thread_id: str,
    ) -> list[MessageRecord]:
        return self.repository.list_messages(principal.tenant_id, thread_id)

    def prepare_turn(
        self,
        principal: PrincipalContext,
        request: ChatRequest,
    ) -> AgentTurnContext:
        self.repository.get_thread(principal.tenant_id, request.thread_id)
        agent = resolve_agent(request.requested_agent)
        return AgentTurnContext(
            request_id=new_id("request"),
            execution_id=new_id("execution"),
            thread_id=request.thread_id,
            tenant_id=principal.tenant_id,
            user_id=principal.user_id,
            requested_agent=agent.agent_id,
            resolved_agent=agent.agent_id,
            turn_owner=agent.agent_id,
            display_agent=agent.agent_id,
            route_family="explicit_agent" if request.requested_agent else "default_orchestrator",
        )

    def complete_chat(
        self,
        principal: PrincipalContext,
        request: ChatRequest,
    ) -> ResponseEnvelope:
        started = perf_counter()
        context = self.prepare_turn(principal, request)
        self.repository.add_message(
            MessageRecord(
                message_id=new_id("message"),
                thread_id=context.thread_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                role="user",
                content=request.content,
                execution_id=context.execution_id,
            )
        )

        if request.simulate_error:
            content = ""
            status = "error"
            error = {
                "code": "SIMULATED_CHAT_FAILURE",
                "message": "Controlled RC0 failure.",
            }
        else:
            content = (
                f"[{context.turn_owner}] Recebi sua mensagem no tenant "
                f"{context.tenant_id}. RC0 opera com resposta determinística local."
            )
            status = "success"
            error = None

        assistant_message = self.repository.add_message(
            MessageRecord(
                message_id=new_id("message"),
                thread_id=context.thread_id,
                tenant_id=context.tenant_id,
                user_id=context.user_id,
                role="assistant",
                content=content,
                agent_id=context.turn_owner,
                agent_name=context.turn_owner,
                display_name=context.turn_owner,
                final_speaker=context.turn_owner,
                turn_owner=context.turn_owner,
                execution_id=context.execution_id,
            )
        )
        return ResponseEnvelope(
            message_id=assistant_message.message_id,
            request_id=context.request_id,
            execution_id=context.execution_id,
            thread_id=context.thread_id,
            tenant_id=context.tenant_id,
            agent_id=context.turn_owner,
            agent_name=context.turn_owner,
            display_name=context.turn_owner,
            final_speaker=context.turn_owner,
            turn_owner=context.turn_owner,
            route_family=context.route_family,
            content=content,
            status=status,
            error=error,
            latency_ms=int((perf_counter() - started) * 1000),
        )
