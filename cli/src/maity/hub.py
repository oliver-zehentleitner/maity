"""HTTP to the hub, standard library only (docs/api.md)."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from email.message import Message
from typing import Any

from maity import __version__, sign
from maity.state import Secret

API = "/api/v1"
LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
CLIENT = f"maity-cli/{__version__}"
USER_AGENT = CLIENT
# §1.5: exempt from Idempotency-Key, because a repeat is harmless or opens a fresh session.
NO_IDEMPOTENCY = ("/me/resume", "/join/")


class HubError(Exception):
    """The hub could not be reached or answered with an error."""

    def __init__(self, message: str, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details: dict[str, Any] = {}


def hub_base(url: str) -> str:
    """Reduce a join or hub URL to the hub's base URL; refuse anything but HTTPS off loopback.

    Credentials travel over TLS only; plain HTTP is accepted for a hub on this machine.
    """
    parts = urllib.parse.urlsplit(url.strip())
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HubError(f"not a hub URL: {url!r}")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        raise HubError(f"refusing plain HTTP to {parts.hostname}; the hub must be served over TLS")
    if parts.username or parts.password:
        raise HubError("refusing a URL with credentials in it")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def join_token(url: str) -> str:
    """The token from `https://<hub>/j/<token>` or `https://<hub>/api/v1/join/<token>`."""
    path = urllib.parse.urlsplit(url.strip()).path.rstrip("/")
    for prefix in ("/j/", f"{API}/join/"):
        if path.startswith(prefix) and "/" not in path[len(prefix) :] and path[len(prefix) :]:
            return urllib.parse.unquote(path[len(prefix) :])
    raise HubError(f"not a join URL (expected /j/<token>): {url!r}")


def segment(value: str) -> str:
    """One path segment, percent-encoded the way the canonical string expects it."""
    return urllib.parse.quote(value, safe="-_.~")


def _error_from(exc: urllib.error.HTTPError, what: str) -> HubError:
    code = exc.headers.get("Maity-Error") if exc.headers else None
    message = f"{exc.code} {exc.reason}"
    details: dict[str, Any] = {}
    try:
        envelope = json.loads(exc.read() or b"{}")
        error = envelope.get("error", {}) if isinstance(envelope, dict) else {}
        code = error.get("code", code)
        message = error.get("message", message)
        details = error.get("details") or {}
    except (ValueError, OSError):
        pass
    err = HubError(f"{what}: {code or 'error'}: {message}", code=code, status=exc.code)
    err.details = details if isinstance(details, dict) else {}
    return err


def _guard_payload(body: bytes, query: str) -> None:
    """Refuse locally what the hub would refuse and, for a real credential, revoke it for."""
    if sign.contains_credential(body.decode("utf-8", errors="replace")) or sign.contains_credential(
        urllib.parse.unquote(query)
    ):
        raise HubError(
            "refusing to send: the request contains a string in the credential format "
            "(mty1.<id>.<secret>); remove it — the hub would revoke a real one"
        )


def get_text(url: str, timeout: float = 30.0) -> str:
    """GET `url`, which callers build from `hub_base()`, so its scheme is http(s) only."""
    headers = {"Accept": "text/markdown, text/plain", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body: bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise _error_from(exc, url) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise HubError(f"cannot reach {url}: {reason}") from exc


@dataclass(frozen=True)
class JoinResult:
    credential: Secret
    credential_id: str | None
    member_id: str | None
    project: str | None
    hub: str | None


def exchange(base: str, token: str, code: str, timeout: float = 30.0) -> JoinResult:
    """POST /join/{token}; the response body is the credential and nothing else (§3.3).

    The body is checked for the credential format and handed back as a `Secret`; it is never
    decoded into anything that could be printed, and an error body is never mistaken for it.
    """
    url = f"{base}{API}/join/{segment(token)}"
    body = json.dumps({"code": code, "client": CLIENT}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)  # noqa: S310
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            raw: bytes = response.read()
            facts: Message = response.headers
    except urllib.error.HTTPError as exc:
        raise _error_from(exc, "join") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HubError(f"cannot reach {base}: {getattr(exc, 'reason', exc)}") from exc
    value = raw.decode("utf-8", errors="replace").strip()
    if not sign.is_credential(value):
        raise HubError("the join exchange answered with something that is not a credential")
    return JoinResult(
        credential=Secret(value),
        credential_id=facts.get("Maity-Credential-Id"),
        member_id=facts.get("Maity-Member-Id"),
        project=facts.get("Maity-Project"),
        hub=facts.get("Maity-Hub"),
    )


def _parse_server_time(value: object) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


@dataclass
class Client:
    """Signed requests to one hub with one credential (§2.2). Every POST and PATCH that is not
    exempt carries an `Idempotency-Key`, reused when the same call is retried."""

    base: str
    key: sign.SigningKey
    clock_offset: float = 0.0
    timeout: float = 30.0
    _opener: urllib.request.OpenerDirector = field(
        default_factory=urllib.request.build_opener, repr=False
    )

    def call(
        self,
        method: str,
        path: str,
        query: Sequence[tuple[str, str]] = (),
        body: Any = None,
        timeout: float | None = None,
    ) -> Any:
        """Send one request; return the decoded JSON body. `path` is relative to /api/v1."""
        method = method.upper()
        if not path.startswith("/"):
            raise HubError(f"path must start with '/': {path!r}")
        full_path = path if path.startswith(f"{API}/") else f"{API}{path}"
        query_string = sign.canonical_query(query)
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        _guard_payload(data, query_string)
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        if method in ("POST", "PATCH") and not any(p in path for p in NO_IDEMPOTENCY):
            headers["Idempotency-Key"] = uuid.uuid4().hex
        url = f"{self.base}{full_path}" + (f"?{query_string}" if query_string else "")
        for attempt in (1, 2):
            stamp = int(time.time() + self.clock_offset)
            signed = sign.sign_headers(self.key, method, full_path, query_string, data, stamp)
            request = urllib.request.Request(  # noqa: S310
                url, data=data if body is not None else None, method=method
            )
            for name, value in {**headers, **signed}.items():
                request.add_header(name, value)
            try:
                with self._opener.open(request, timeout=timeout or self.timeout) as response:
                    raw: bytes = response.read()
                    return json.loads(raw) if raw else None
            except urllib.error.HTTPError as exc:
                err = _error_from(exc, f"{method} {full_path}")
                server = _parse_server_time(err.details.get("server_time"))
                if err.code == "timestamp_skew" and attempt == 1 and server is not None:
                    self.clock_offset = server - time.time()
                    continue
                raise err from exc
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                raise HubError(f"cannot reach {self.base}: {getattr(exc, 'reason', exc)}") from exc
            except ValueError as exc:
                raise HubError(f"{method} {full_path}: the hub answered with invalid JSON") from exc
        raise AssertionError("unreachable")
