from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from sqlalchemy import delete, func, insert, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from orkio_platform.domain.errors import ConflictError, NotFoundError
from orkio_platform.domain.models import (
    ExecutionRecord,
    MessageRecord,
    RecoveryDecisionRecord,
    ThreadRecord,
    utc_now,
)
from orkio_platform.infrastructure.database import (
    executions,
    messages,
    metadata,
    recovery_decisions,
    threads,
)

FailureInjector = Callable[[str], None]


class SQLAlchemyRepository:
    def __init__(
        self,
        engine: Engine,
        *,
        failure_injector: FailureInjector | None = None,
    ) -> None:
        self.engine = engine
        self._failure_injector = failure_injector

    @property
    def backend_name(self) -> str:
        return self.engine.dialect.name

    def create_schema_for_tests(self) -> None:
        metadata.create_all(self.engine)

    def drop_schema_for_tests(self) -> None:
        metadata.drop_all(self.engine)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(select(1))
        return True

    def reset(self) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(recovery_decisions))
            connection.execute(delete(messages))
            connection.execute(delete(executions))
            connection.execute(delete(threads))

    def create_thread(self, thread: ThreadRecord) -> ThreadRecord:
        with self.engine.begin() as connection:
            connection.execute(insert(threads).values(**thread.model_dump()))
        return thread

    def get_thread(self, tenant_id: str, thread_id: str) -> ThreadRecord:
        statement = select(threads).where(
            threads.c.tenant_id == tenant_id,
            threads.c.thread_id == thread_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise NotFoundError("THREAD_NOT_FOUND", "Thread not found.")
        return ThreadRecord(**dict(row))

    def list_threads(self, tenant_id: str) -> list[ThreadRecord]:
        statement = (
            select(threads)
            .where(threads.c.tenant_id == tenant_id)
            .order_by(threads.c.created_at.desc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [ThreadRecord(**dict(row)) for row in rows]

    def update_thread_title(
        self,
        tenant_id: str,
        thread_id: str,
        title: str,
    ) -> ThreadRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(threads)
                .where(
                    threads.c.tenant_id == tenant_id,
                    threads.c.thread_id == thread_id,
                )
                .values(title=title)
            )
            if result.rowcount != 1:
                raise NotFoundError(
                    "THREAD_NOT_FOUND",
                    "Thread not found.",
                )
        return self.get_thread(tenant_id, thread_id)

    def add_message(self, message: MessageRecord) -> MessageRecord:
        self.get_thread(message.tenant_id, message.thread_id)
        with self.engine.begin() as connection:
            connection.execute(insert(messages).values(**message.model_dump()))
        return message

    def get_message(self, tenant_id: str, message_id: str) -> MessageRecord:
        statement = select(messages).where(
            messages.c.tenant_id == tenant_id,
            messages.c.message_id == message_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise NotFoundError("MESSAGE_NOT_FOUND", "Message not found.")
        return MessageRecord(**dict(row))

    def list_messages(
        self,
        tenant_id: str,
        thread_id: str,
    ) -> list[MessageRecord]:
        self.get_thread(tenant_id, thread_id)
        statement = (
            select(messages)
            .where(
                messages.c.tenant_id == tenant_id,
                messages.c.thread_id == thread_id,
            )
            .order_by(messages.c.created_at.asc(), messages.c.message_id.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [MessageRecord(**dict(row)) for row in rows]

    def reserve_execution(
        self,
        execution: ExecutionRecord,
    ) -> tuple[ExecutionRecord, bool]:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    insert(executions).values(**execution.model_dump())
                )
            return execution, True
        except IntegrityError:
            existing = self.get_execution(
                execution.tenant_id,
                execution.request_id,
            )
            if existing is None:
                raise
            return existing, False

    def get_execution(
        self,
        tenant_id: str,
        request_id: str,
    ) -> ExecutionRecord | None:
        statement = select(executions).where(
            executions.c.tenant_id == tenant_id,
            executions.c.request_id == request_id,
        )
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        return None if row is None else ExecutionRecord(**dict(row))

    def heartbeat_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        lease_owner: str,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(executions)
                .where(
                    executions.c.tenant_id == tenant_id,
                    executions.c.request_id == request_id,
                    executions.c.status == "running",
                    executions.c.lease_owner == lease_owner,
                )
                .values(
                    heartbeat_at=heartbeat_at,
                    lease_expires_at=lease_expires_at,
                )
            )
            if result.rowcount != 1:
                current = connection.execute(
                    select(executions).where(
                        executions.c.tenant_id == tenant_id,
                        executions.c.request_id == request_id,
                    )
                ).mappings().first()
                if current is None:
                    raise NotFoundError(
                        "EXECUTION_NOT_FOUND",
                        "Execution not found.",
                    )
                if current["status"] != "running":
                    raise ConflictError(
                        "EXECUTION_NOT_RUNNING",
                        "Execution is not running.",
                    )
                raise ConflictError(
                    "EXECUTION_LEASE_LOST",
                    "Execution lease is owned by another worker.",
                )
        refreshed = self.get_execution(tenant_id, request_id)
        assert refreshed is not None
        return refreshed

    def _terminal_update(
        self,
        connection,
        execution: ExecutionRecord,
        *,
        status: str,
        error_code: str | None,
        error_message: str | None,
        user_message_id: str | None,
        assistant_message_id: str | None,
    ) -> None:
        result = connection.execute(
            update(executions)
            .where(
                executions.c.tenant_id == execution.tenant_id,
                executions.c.request_id == execution.request_id,
                executions.c.status == "running",
                executions.c.lease_owner == execution.lease_owner,
            )
            .values(
                status=status,
                error_code=error_code,
                error_message=error_message,
                user_message_id=user_message_id,
                assistant_message_id=assistant_message_id,
                completed_at=utc_now(),
            )
        )
        if result.rowcount != 1:
            raise ConflictError(
                "EXECUTION_NOT_RUNNING",
                "Execution is not available for terminal completion.",
            )

    def complete_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(messages).values(**user_message.model_dump())
            )
            connection.execute(
                insert(messages).values(**assistant_message.model_dump())
            )
            if self._failure_injector is not None:
                self._failure_injector("before_success_terminal_update")
            self._terminal_update(
                connection,
                execution,
                status="success",
                error_code=None,
                error_message=None,
                user_message_id=user_message.message_id,
                assistant_message_id=assistant_message.message_id,
            )
        completed = self.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        assert completed is not None
        return completed

    def partial_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(messages).values(**user_message.model_dump())
            )
            connection.execute(
                insert(messages).values(**assistant_message.model_dump())
            )
            if self._failure_injector is not None:
                self._failure_injector("before_partial_terminal_update")
            self._terminal_update(
                connection,
                execution,
                status="partial",
                error_code=assistant_message.error_code,
                error_message=assistant_message.error_message,
                user_message_id=user_message.message_id,
                assistant_message_id=assistant_message.message_id,
            )
        completed = self.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        assert completed is not None
        return completed

    def fail_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        error_message: MessageRecord,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(messages).values(**user_message.model_dump())
            )
            connection.execute(
                insert(messages).values(**error_message.model_dump())
            )
            if self._failure_injector is not None:
                self._failure_injector("before_error_terminal_update")
            self._terminal_update(
                connection,
                execution,
                status="error",
                error_code=error_message.error_code,
                error_message=error_message.error_message,
                user_message_id=user_message.message_id,
                assistant_message_id=error_message.message_id,
            )
        completed = self.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        assert completed is not None
        return completed

    def cancel_execution(
        self,
        execution: ExecutionRecord,
        cancellation_message: MessageRecord,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(messages).values(
                    **cancellation_message.model_dump()
                )
            )
            if self._failure_injector is not None:
                self._failure_injector("before_cancel_terminal_update")
            self._terminal_update(
                connection,
                execution,
                status="cancelled",
                error_code="EXECUTION_CANCELLED",
                error_message=cancellation_message.error_message,
                user_message_id=execution.user_message_id,
                assistant_message_id=cancellation_message.message_id,
            )
        cancelled = self.get_execution(
            execution.tenant_id,
            execution.request_id,
        )
        assert cancelled is not None
        return cancelled

    def abort_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> ExecutionRecord:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(executions)
                .where(
                    executions.c.tenant_id == tenant_id,
                    executions.c.request_id == request_id,
                    executions.c.status == "running",
                )
                .values(
                    status="error",
                    error_code=error_code,
                    error_message=error_message,
                    completed_at=utc_now(),
                )
            )
            if result.rowcount not in {0, 1}:
                raise RuntimeError("UNEXPECTED_EXECUTION_UPDATE_COUNT")
        existing = self.get_execution(tenant_id, request_id)
        if existing is None:
            raise NotFoundError(
                "EXECUTION_NOT_FOUND",
                "Execution not found.",
            )
        return existing

    def record_recovery_decision(
        self,
        decision: RecoveryDecisionRecord,
    ) -> RecoveryDecisionRecord:
        with self.engine.begin() as connection:
            connection.execute(
                insert(recovery_decisions).values(**decision.model_dump())
            )
        return decision

    def list_recovery_decisions(
        self,
        tenant_id: str,
        request_id: str,
    ) -> list[RecoveryDecisionRecord]:
        statement = (
            select(recovery_decisions)
            .where(
                recovery_decisions.c.tenant_id == tenant_id,
                recovery_decisions.c.request_id == request_id,
            )
            .order_by(recovery_decisions.c.created_at.asc())
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [RecoveryDecisionRecord(**dict(row)) for row in rows]

    def stats(self, tenant_id: str) -> dict[str, int]:
        with self.engine.connect() as connection:
            thread_count = connection.execute(
                select(func.count())
                .select_from(threads)
                .where(threads.c.tenant_id == tenant_id)
            ).scalar_one()
            message_count = connection.execute(
                select(func.count())
                .select_from(messages)
                .where(messages.c.tenant_id == tenant_id)
            ).scalar_one()
            execution_count = connection.execute(
                select(func.count())
                .select_from(executions)
                .where(executions.c.tenant_id == tenant_id)
            ).scalar_one()
            decision_count = connection.execute(
                select(func.count())
                .select_from(recovery_decisions)
                .where(recovery_decisions.c.tenant_id == tenant_id)
            ).scalar_one()
        return {
            "threads": int(thread_count),
            "messages": int(message_count),
            "executions": int(execution_count),
            "recovery_decisions": int(decision_count),
        }
