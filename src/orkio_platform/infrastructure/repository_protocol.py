from datetime import datetime
from typing import Protocol

from orkio_platform.domain.models import (
    ExecutionRecord,
    MessageRecord,
    RecoveryDecisionRecord,
    ThreadRecord,
)


class RepositoryProtocol(Protocol):
    @property
    def backend_name(self) -> str: ...

    def reset(self) -> None: ...
    def ping(self) -> bool: ...
    def create_thread(self, thread: ThreadRecord) -> ThreadRecord: ...
    def get_thread(self, tenant_id: str, thread_id: str) -> ThreadRecord: ...
    def list_threads(self, tenant_id: str) -> list[ThreadRecord]: ...
    def add_message(self, message: MessageRecord) -> MessageRecord: ...
    def get_message(self, tenant_id: str, message_id: str) -> MessageRecord: ...
    def list_messages(
        self,
        tenant_id: str,
        thread_id: str,
    ) -> list[MessageRecord]: ...
    def reserve_execution(
        self,
        execution: ExecutionRecord,
    ) -> tuple[ExecutionRecord, bool]: ...
    def get_execution(
        self,
        tenant_id: str,
        request_id: str,
    ) -> ExecutionRecord | None: ...
    def heartbeat_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        lease_owner: str,
        heartbeat_at: datetime,
        lease_expires_at: datetime,
    ) -> ExecutionRecord: ...
    def complete_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> ExecutionRecord: ...
    def fail_execution(
        self,
        execution: ExecutionRecord,
        user_message: MessageRecord,
        error_message: MessageRecord,
    ) -> ExecutionRecord: ...
    def cancel_execution(
        self,
        execution: ExecutionRecord,
        cancellation_message: MessageRecord,
    ) -> ExecutionRecord: ...
    def abort_execution(
        self,
        tenant_id: str,
        request_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> ExecutionRecord: ...
    def record_recovery_decision(
        self,
        decision: RecoveryDecisionRecord,
    ) -> RecoveryDecisionRecord: ...
    def list_recovery_decisions(
        self,
        tenant_id: str,
        request_id: str,
    ) -> list[RecoveryDecisionRecord]: ...
    def stats(self, tenant_id: str) -> dict[str, int]: ...
