from __future__ import annotations

from collections import defaultdict
from threading import RLock

from orkio_platform.domain.errors import NotFoundError
from orkio_platform.domain.models import MessageRecord, ThreadRecord


class InMemoryRepository:
    """Controlled RC0 adapter. It is not a production persistence layer."""

    def __init__(self) -> None:
        self._lock = RLock()
        self._threads: dict[tuple[str, str], ThreadRecord] = {}
        self._messages: dict[tuple[str, str], list[MessageRecord]] = defaultdict(list)

    def reset(self) -> None:
        with self._lock:
            self._threads.clear()
            self._messages.clear()

    def create_thread(self, thread: ThreadRecord) -> ThreadRecord:
        key = (thread.tenant_id, thread.thread_id)
        with self._lock:
            self._threads[key] = thread
        return thread

    def get_thread(self, tenant_id: str, thread_id: str) -> ThreadRecord:
        with self._lock:
            thread = self._threads.get((tenant_id, thread_id))
        if thread is None:
            if any(existing_id == thread_id for _, existing_id in self._threads):
                raise NotFoundError(
                    "THREAD_NOT_FOUND",
                    "Thread does not exist in the current tenant.",
                )
            raise NotFoundError("THREAD_NOT_FOUND", "Thread does not exist.")
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

    def add_message(self, message: MessageRecord) -> MessageRecord:
        self.get_thread(message.tenant_id, message.thread_id)
        with self._lock:
            self._messages[(message.tenant_id, message.thread_id)].append(message)
        return message

    def list_messages(self, tenant_id: str, thread_id: str) -> list[MessageRecord]:
        self.get_thread(tenant_id, thread_id)
        with self._lock:
            return list(self._messages[(tenant_id, thread_id)])

    def stats(self, tenant_id: str) -> dict[str, int]:
        with self._lock:
            thread_count = sum(1 for key in self._threads if key[0] == tenant_id)
            message_count = sum(
                len(messages)
                for key, messages in self._messages.items()
                if key[0] == tenant_id
            )
        return {"threads": thread_count, "messages": message_count}


repository = InMemoryRepository()
