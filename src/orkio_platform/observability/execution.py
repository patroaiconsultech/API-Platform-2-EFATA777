from __future__ import annotations

import json
import logging
from typing import Any

from orkio_platform.domain.models import ExecutionRecord

logger = logging.getLogger("orkio.execution")


def log_execution_event(
    event: str,
    execution: ExecutionRecord,
    **extra: Any,
) -> None:
    payload = {
        "event": event,
        "tenant_id": execution.tenant_id,
        "request_id": execution.request_id,
        "execution_id": execution.execution_id,
        "thread_id": execution.thread_id,
        "requested_agent": execution.requested_agent,
        "resolved_agent": execution.resolved_agent,
        "turn_owner": execution.turn_owner,
        "route_family": execution.route_family,
        "status": execution.status,
        **extra,
    }
    logger.info(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
