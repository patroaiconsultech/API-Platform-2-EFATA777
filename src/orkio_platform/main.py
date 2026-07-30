from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from orkio_platform.api.routes import admin, agents, chat, governance, health, threads
from orkio_platform.config import get_settings
from orkio_platform.domain.errors import DomainError


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(DomainError)
    async def domain_error_handler(
        _: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                }
            },
        )

    app.include_router(health.router)
    app.include_router(agents.router)
    app.include_router(threads.router)
    app.include_router(chat.router)
    app.include_router(admin.router)
    app.include_router(governance.router)

    return app


app = create_app()
