"""The error envelope (docs/api.md §1.3).

Every error is `{"error": {"code", "message", "details"}}` with the code
repeated in the `Maity-Error` header. A message never quotes the request
body.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import InterfaceError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

ERROR_HEADER = "Maity-Error"

log = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}
        self.headers = headers or {}


def error_response(
    status: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}}},
        status_code=status,
        headers={ERROR_HEADER: code, **(headers or {})},
    )


# The contract's errors, by the situation that raises them.
def invalid(fields: dict[str, Any], message: str = "the request does not validate") -> ApiError:
    return ApiError(400, "invalid", message, {"fields": fields})


def unauthenticated(message: str = "no valid credential or session") -> ApiError:
    return ApiError(401, "unauthenticated", message)


def forbidden(scope: str | None = None, message: str | None = None) -> ApiError:
    details = {"scope": scope} if scope else {}
    return ApiError(403, "forbidden", message or "the role lacks the scope", details)


def humans_only(message: str) -> ApiError:
    """A call no agent may make, whatever its role (§2.3)."""
    return ApiError(403, "forbidden", message, {"reason": "humans_only"})


def not_found() -> ApiError:
    return ApiError(404, "not_found", "no such resource")


def probe_not_configured(reason: str | None) -> ApiError:
    """No source covers the project's repository (§11.4). `reason` only for a
    `project:admin`; every other reader gets `details: {}`."""
    return ApiError(
        409,
        "probe_not_configured",
        "no forge access covers this repository",
        {"reason": reason} if reason is not None else None,
    )


def rate_limited(retry_after: int) -> ApiError:
    return ApiError(
        429,
        "rate_limited",
        "too many attempts",
        headers={"Retry-After": str(retry_after)},
    )


def driver_code(error: Exception) -> str:
    """The driver's numeric code or SQLSTATE, never its text (which can quote values)."""
    original = getattr(error, "orig", None)
    sqlstate = getattr(original, "sqlstate", None)
    if isinstance(sqlstate, str):
        return sqlstate
    args = getattr(original, "args", ())
    return str(args[0]) if args and isinstance(args[0], int) else ""


# What a connection failure can be, found by phrases the drivers use. Nothing of the driver's text
# is kept: the category is chosen from this list and only its name is logged, so a password, a
# user, a host or a connection string in the text cannot reach the log, whatever escaping it uses.
_CAUSES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "dns",
        (
            "failed to resolve host",
            "name or service not known",
            "temporary failure in name",
            "name resolution",
            "could not translate host name",
            "nodename nor servname",
            "getaddrinfo failed",
        ),
    ),
    ("timeout", ("timeout expired", "timed out")),
    ("refused", ("connection refused",)),
    ("unreachable", ("network is unreachable", "no route to host")),
    ("closed", ("server closed the connection", "connection lost", "eof detected", "broken pipe")),
    ("starting", ("starting up", "shutting down", "recovery mode")),
    ("no_slots", ("remaining connection slots", "too many clients", "too many connections")),
    ("auth", ("authentication failed", "access denied")),
    ("ssl", ("ssl", "tls")),
)


def connection_cause(original: BaseException) -> str:
    """The category (`_CAUSES`) of a failure to connect, from the driver's own exception, or
    `unclassified`; only the name of the category is ever kept, never the driver's text."""
    text = str(original).lower()
    return next(
        (name for name, phrases in _CAUSES if any(p in text for p in phrases)), "unclassified"
    )


def driver_reason(error: Exception) -> str:
    """Why a connection failed, for the log and never for a client: the original exception's class
    and one category from a fixed list (`_CAUSES`), or `unclassified`. The driver's own text is
    never logged: it can quote the connection string, the user or the password in forms no
    pattern covers.
    """
    original = getattr(error, "orig", None)
    if original is None:
        return ""
    kind = type(original)
    return f"{kind.__module__}.{kind.__qualname__} {connection_cause(original)}"


def install(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_request: Request, error: ApiError) -> JSONResponse:
        return error_response(error.status, error.code, error.message, error.details, error.headers)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, error: RequestValidationError) -> JSONResponse:
        fields: dict[str, str] = {}
        for item in error.errors():
            location = [str(part) for part in item.get("loc", ()) if part not in ("body", "query")]
            # The reason is pydantic's type of failure, never the input value.
            fields[".".join(location) or "body"] = str(item.get("type", "invalid"))
        return error_response(400, "invalid", "the request does not validate", {"fields": fields})

    @app.exception_handler(OperationalError)
    @app.exception_handler(InterfaceError)
    async def _database(_request: Request, error: Exception) -> JSONResponse:
        # Connection-level failures. The client never gets the driver's text (§1.3); the log gets it
        # masked, because without the cause a burst of these cannot be told apart.
        log.error(
            "database unavailable: %s %s %s",
            type(error).__name__,
            driver_code(error),
            driver_reason(error),
        )
        return error_response(503, "database_unavailable", "the database is unreachable")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, error: StarletteHTTPException) -> JSONResponse:
        if error.status_code == 404:
            return error_response(404, "not_found", "no such resource")
        if error.status_code == 405:
            allow = (error.headers or {}).get("Allow")
            return error_response(
                405,
                "method_not_allowed",
                "the path exists, the method does not",
                headers={"Allow": allow} if allow else None,
            )
        return error_response(error.status_code, "http_error", str(error.detail))
