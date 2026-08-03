from fastapi import APIRouter, Depends
from orkio_platform.api.dependencies import get_principal
from orkio_platform.application.services import PlatformService
from orkio_platform.domain.models import (
    MessageRecord,
    PrincipalContext,
    ThreadCreate,
    ThreadRecord,
    ThreadUpdate,
)
from orkio_platform.infrastructure.repositories import repository

router = APIRouter(prefix="/api/threads", tags=["threads"])
service = PlatformService(repository)

@router.post("", response_model=ThreadRecord)
def create_thread(payload: ThreadCreate, principal: PrincipalContext = Depends(get_principal)) -> ThreadRecord:
    return service.create_thread(principal, payload.title)

@router.get("", response_model=list[ThreadRecord])
def list_threads(principal: PrincipalContext = Depends(get_principal)) -> list[ThreadRecord]:
    return service.list_threads(principal)



@router.patch("/{thread_id}", response_model=ThreadRecord)
def rename_thread(
    thread_id: str,
    payload: ThreadUpdate,
    principal: PrincipalContext = Depends(get_principal),
) -> ThreadRecord:
    return service.rename_thread(
        principal,
        thread_id,
        payload.title,
    )

@router.get("/{thread_id}/messages", response_model=list[MessageRecord])
def list_messages(thread_id: str, principal: PrincipalContext = Depends(get_principal)) -> list[MessageRecord]:
    return service.list_messages(principal, thread_id)
