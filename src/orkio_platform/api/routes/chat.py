from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from orkio_platform.api.dependencies import get_principal
from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import ChatRequest, PrincipalContext, ResponseEnvelope
from orkio_platform.infrastructure.repositories import repository
from orkio_platform.realtime.sse import stream_chat

router = APIRouter(prefix="/api/chat", tags=["chat"])
service = PlatformService(repository)


@router.post("", response_model=ResponseEnvelope)
def chat(
    payload: ChatRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> ResponseEnvelope:
    return service.complete_chat(principal, payload)


@router.post("/stream")
def chat_stream(
    payload: ChatRequest,
    principal: PrincipalContext = Depends(get_principal),
) -> StreamingResponse:
    return StreamingResponse(
        stream_chat(service, principal, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
