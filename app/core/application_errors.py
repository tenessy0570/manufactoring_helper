from enum import StrEnum


class ErrorKind(StrEnum):
    INVALID_OPERATION = "invalid_operation"
    INVALID_INPUT = "invalid_input"
    UNAUTHENTICATED = "unauthenticated"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMITED = "rate_limited"


class ApplicationError(Exception):
    """A deliberate public message; unexpected internal errors must not use this type."""

    def __init__(self, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.kind, self.message = kind, message
