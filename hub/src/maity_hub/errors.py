"""The error envelope (docs/api.md §1.3).

Every error is `{"error": {"code", "message", "details"}}` with the code
repeated in the `Maity-Error` header. A message never quotes the request
body.
"""

from __future__ import annotations

import logging
import re
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


_DSN = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s'\"]*")
_KEYWORD = re.compile(r"(?i)\b(password|passwd|pwd|secret|token)\s*=\s*(?:'[^']*'|\"[^\"]*\"|\S+)")
_REASON_LIMIT = 300


def driver_reason(error: Exception) -> str:
    """What the driver says about a connection failure, for the log and never for a client:
    the original exception's type and its text with every URL (a DSN with credentials) and every
    `password=...` pair replaced, on one line and cut short. Connection errors name hosts, ports and
    timeouts; the masking covers the case that a driver ever quotes the connection string."""
    original = getattr(error, "orig", None)
    if original is None:
        return ""
    text = " ".join(str(original).split())
    text = _DSN.sub("<url>", text)
    text = _KEYWORD.sub(lambda m: f"{m.group(1)}=<hidden>", text)
    if len(text) > _REASON_LIMIT:
        text = text[:_REASON_LIMIT] + "..."
    return f"{type(original).__name__}: {text}" if text else type(original).__name__


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
