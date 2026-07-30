from __future__ import annotations


class DomainError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class NotFoundError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=404)


class ForbiddenError(DomainError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(code, message, status_code=403)
