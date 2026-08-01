from __future__ import annotations

from collections import defaultdict
import json
import logging
from datetime import datetime
from threading import RLock

from orkio_platform.config import get_settings
from orkio_platform.domain.errors import ConflictError, NotFoundError
from orkio_platform.domain.models import (
    ExecutionRecord,
    MessageRecord,
    RecoveryDecisionRecord,
    ThreadRecord,
    utc_now,
)
from orkio_platform.infrastructure.database import (
    create_database_engine,
    database_driver_descriptor,
)
from orkio_platform.infrastructure.repository_protocol import RepositoryProtocol
from orkio_platform.infrastructure.sqlalchemy_repository import (
    SQLAlchemyRepository,
)


logger = logging.getLogger("orkio.database")


class InMemoryRepository:
    @property
    def backend_name(self) -> str:
        return "memory"

    def __init__(self) -> None:
        self._lock = RLock()
        self._threads: dict[tuple[str, str], ThreadRecord] = {}
        self._messages: dict[
            tuple[str, str],
            list[MessageRecord],
        ] = defaultdict(list)
        self._messages_by_id: dict[
            tuple[str, str],
            MessageRecord,
        ] = {}
        self._executions: dict[
            tuple[str, str],
            ExecutionRecord,
        ] = {}
        self._recovery_decisions: dict[
            tuple[str, str],
            RecoveryDecisionRecord,
        ] = {}

    def ping(self) -> bool:
        return True

    def reset(self) -> None:
        with self._lock:
            self._threads.clear()
            self._messages.clear()
            self._messages_by_id.clear()
            self._executions.clear()
            self._recovery_decisions.clear()

    def create_thread(self, thread: ThreadRecord) -> ThreadRecord:
        with self._lock:
            self._threads[(thread.tenant_id, thread.thread_id)] = thread
        return thread

    def get_thread(self, tenant_id: str, thread_id: str) -> ThreadRecord:
        with self._lock:
            thread = self._threads.get((tenant_id, thread_id))
        if thread is None:
            raise NotFoundError("THREAD_NOT_FOUND", "Thread not found.")
        return thread

    def list_threads(self, tenant_id: str) -> list[ThreadRecord]:
        with self._lock:
            return sorted(
                [
                    thread
                    for (thread_tenant, _), thread in self._threads.items()
                    if thread_tenant == tenant_id
                ],
                key=lambda item: item.created_at,
                reverse=True,
            )

    def _append_message_locked(self, message: MessageRecord) -> None:
        key = (message.tenant_id, message.message_id)
        if key in self._messages_by_id:
            raise ConflictError(
                "MESSAGE_ALREADY_EXISTS",
                "Message already exists.",
            )
        if message.execution_id is not None:
            role_key = (
                message.tenant_id,
                message.execution_id,
                message.role,
            )
            for existing in self._messages_by_id.values():
                if (
                    existing.tenant_id,
                    existing.execution_id,
                    existing.role,
                ) == role_key:
                    raise ConflictError(
                        "EXECUTION_ROLE_ALREADY_PERSISTED",
                        "Execution role is already persisted.",
                    )
        self._messages[
            (message.tenant_id, message.thread_id)
        ].append(message)
        self._messages_by_id[key] = message

    def add_message(self, message: MessageRecord) -> MessageRecord:
        self.get_thread(message.tenant_id, message.thread_id)
        with self._lock:
            self._append_message_locked(message)
        return message

    def get_message(self, tenant_id: str, message_id: str) -> MessageRecord:
        with self._lock:
            message = self._messages_by_id.get((tenant_id, message_id))
        if message is None:
            raise NotFoundError("MESSAGE_NOT_FOUND", "Message not found.")
        return message

    def list_messages(
        self,
        tenant_id: str,
        thread_id: str,
    ) -> list[MessageRecord]:
        self.get_thread(tenant_id, thread_id)
        with self._lock:
            return list(self._messages[(tenant_id, thread_id)])

    def reserve_execution(
        self,
        execution: ExecutionRecord,
    ) -> tuple[ExecutionRecord, bool]:
        key = (execution.tenant_id, execution.request_id)
        with self._lock:
            existing = self._executions.get(key)
            if existing is not None:
                return existing, False
            self._executions[key] = execution
        return execution, True

    def get_execution(
        self,
        tenant_id: str,
        request_id: str,
    ) -> ExecutionRecord | None:
        with self._lock:
            return self._executions.get((tenant_id, request_id))

    def heartbeat_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        lease_owner: str,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> ExecutionRecord:
        with self._lock:
            key = (tenant_id, request_id)
            current = self._executions.get(key)
            if current is None:
                raise NotFoundError(
                    "EXECUTION_NOT_FOUND",
                    "Execution not found.",
                )
            if current.status != "running":
                raise ConflictError(
                    "EXECUTION_NOT_RUNNING",
                    "Execution is not running.",
                )
            if current.lease_owner != lease_owner:
                raise ConflictError(
                    "EXECUTION_LEASE_LOST",
                    "Execution lease is owned by another worker.",
                )
            current = current.model_copy(
                update={
                    "heartbeat_at": heartbeat_at,
                    "lease_expires_at": lease_expires_at,
                }
            )
            self._executions[key] = current
            return current

    def _require_running_locked(
        self,
        execution: ExecutionRecord,
    ) -> ExecutionRecord:
        current = self._executions.get(
            (execution.tenant_id, execution.request_id)
        )
        if current is None:
            raise NotFoundError(
                "EXECUTION_NOT_FOUND",
                "Execution not found.",
            )
        if current.status != "running":
            raise ConflictError(
                "EXECUTION_NOT_RUNNING",
                "Execution is not available for terminal completion.",
            )
        if current.lease_owner != execution.lease_owner:
            raise ConflictError(
                "EXECUTION_LEASE_LOST",
                "Execution lease is owned by another worker.",
            )
        return current

    def complete_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> ExecutionRecord:
        with self._lock:
            current = self._require_running_locked(execution)
            self.get_thread(execution.tenant_id, execution.thread_id)
            self._append_message_locked(user_message)
            try:
                self._append_message_locked(assistant_message)
            except Exception:
                self._messages[
                    (user_message.tenant_id, user_message.thread_id)
                ].remove(user_message)
                self._messages_by_id.pop(
                    (user_message.tenant_id, user_message.message_id),
                    None,
                )
                raise
            completed = current.model_copy(
                update={
                    "status": "success",
                    "user_message_id": user_message.message_id,
                    "assistant_message_id": assistant_message.message_id,
                    "completed_at": utc_now(),
                }
            )
            self._executions[
                (execution.tenant_id, execution.request_id)
            ] = completed
            return completed

    def fail_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        error_message: MessageRecord,
    ) -> ExecutionRecord:
        with self._lock:
            current = self._require_running_locked(execution)
            self.get_thread(execution.tenant_id, execution.thread_id)
            self._append_message_locked(user_message)
            try:
                self._append_message_locked(error_message)
            except Exception:
                self._messages[
                    (user_message.tenant_id, user_message.thread_id)
                ].remove(user_message)
                self._messages_by_id.pop(
                    (user_message.tenant_id, user_message.message_id),
                    None,
                )
                raise
            completed = current.model_copy(
                update={
                    "status": "error",
                    "error_code": error_message.error_code,
                    "error_message": error_message.error_message,
                    "user_message_id": user_message.message_id,
                    "assistant_message_id": error_message.message_id,
                    "completed_at": utc_now(),
                }
            )
            self._executions[
                (execution.tenant_id, execution.request_id)
            ] = completed
            return completed

    def cancel_execution(
        self,
        execution: ExecutionRecord,
        cancellation_message: MessageRecord,
    ) -> ExecutionRecord:
        with self._lock:
            current = self._require_running_locked(execution)
            self.get_thread(execution.tenant_id, execution.thread_id)
            self._append_message_locked(cancellation_message)
            cancelled = current.model_copy(
                update={
                    "status": "cancelled",
                    "error_code": "EXECUTION_CANCELLED",
                    "error_message": cancellation_message.error_message,
                    "assistant_message_id": cancellation_message.message_id,
                    "completed_at": utc_now(),
                }
            )
            self._executions[
                (execution.tenant_id, execution.request_id)
            ] = cancelled
            return cancelled

    def abort_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> ExecutionRecord:
        with self._lock:
            key = (tenant_id, request_id)
            current = self._executions.get(key)
            if current is None:
                raise NotFoundError(
                    "EXECUTION_NOT_FOUND",
                    "Execution not found.",
                )
            if current.status == "running":
                current = current.model_copy(
                    update={
                        "status": "error",
                        "error_code": error_code,
                        "error_message": error_message,
                        "completed_at": utc_now(),
                    }
                )
                self._executions[key] = current
            return current

    def record_recovery_decision(
        self,
        decision: RecoveryDecisionRecord,
    ) -> RecoveryDecisionRecord:
        self.get_execution(decision.tenant_id, decision.request_id)
        with self._lock:
            key = (decision.tenant_id, decision.decision_id)
            if key in self._recovery_decisions:
                raise ConflictError(
                    "RECOVERY_DECISION_ALREADY_EXISTS",
                    "Recovery decision already exists.",
                )
            self._recovery_decisions[key] = decision
        return decision

    def list_recovery_decisions(
        self,
        tenant_id: str,
        request_id: str,
    ) -> list[RecoveryDecisionRecord]:
        with self._lock:
            return sorted(
                [
                    decision
                    for decision in self._recovery_decisions.values()
                    if decision.tenant_id == tenant_id
                    and decision.request_id == request_id
                ],
                key=lambda item: item.created_at,
            )

    def stats(self, tenant_id: str) -> dict[str, int]:
        with self._lock:
            return {
                "threads": sum(
                    1 for key in self._threads if key[0] == tenant_id
                ),
                "messages": sum(
                    len(items)
                    for key, items in self._messages.items()
                    if key[0] == tenant_id
                ),
                "executions": sum(
                    1 for key in self._executions if key[0] == tenant_id
                ),
                "recovery_decisions": sum(
                    1
                    for key in self._recovery_decisions
                    if key[0] == tenant_id
                ),
            }


def build_repository() -> RepositoryProtocol:
    settings = get_settings()
    if settings.database_url:
        descriptor = database_driver_descriptor(settings.database_url)
        logger.info(
            json.dumps(
                {
                    "event": "database_driver_selected",
                    **descriptor,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
        engine = create_database_engine(
            settings.database_url,
            echo=settings.database_echo,
        )
        return SQLAlchemyRepository(engine)
    logger.info(
        json.dumps(
            {
                "event": "database_driver_selected",
                "drivername": "memory",
                "backend": "memory",
                "driver": "memory",
            },
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return InMemoryRepository()


repository: RepositoryProtocol = build_repository()
