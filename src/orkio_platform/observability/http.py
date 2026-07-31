from __future__ import annotations

import json
import logging
from time import perf_counter
from uuid import uuid4

from fastapi import Request

logger = logging.getLogger("orkio.http")


async def request_observability_middleware(request: Request, call_next):
    request_id = (
        request.headers.get("X-Request-ID")
        or f"request_{uuid4().hex}"
    )
    request.state.request_id = request_id
    started = perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        latency_ms = int((perf_counter() - started) * 1000)
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status": status,
                    "latency_ms": latency_ms,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )
