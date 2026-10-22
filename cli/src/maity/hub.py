"""HTTP to the hub, standard library only (docs/api.md)."""

from __future__ import annotations

import ipaddress
import json
import re
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
NO_IDEMPOTENCY = ("/me/resume", "/join/", "/runner/hello", "/runner/placements/")


class HubError(Exception):
    """The hub could not be reached or answered with an error."""

    def __init__(self, message: str, code: str | None = None, status: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.details: dict[str, Any] = {}
        self.retry_after: float | None = None  # seconds, from a 429's or 503's Retry-After


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The hub never redirects an API call. Following one would carry `Authorization` (and the
    signed headers) to another host or down to plain HTTP, so every redirect is an error."""

    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Message,
        newurl: str,
    ) -> urllib.request.Request | None:
        raise HubError(
            f"refusing to follow a redirect ({code}) to {safe_url(newurl)}; check the hub URL",
            status=code,
        )


def opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect)


def safe_url(url: str) -> str:
    """A URL fit for a message: scheme, host, port and path; never userinfo or query."""
    try:
        parts = urllib.parse.urlsplit(url.strip())
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return "<not a URL>"
    return urllib.parse.urlunsplit((parts.scheme, host, parts.path, "", "")) or "<empty>"


def hub_base(url: str) -> str:
    """Reduce a join or hub URL to the hub's base URL; refuse anything but HTTPS off loopback.

    Credentials travel over TLS only; plain HTTP is accepted for a hub on this machine.
    """
    try:
        parts = urllib.parse.urlsplit(url.strip())
        port = parts.port  # raises ValueError on a port that is not a number in range
    except ValueError:
        raise HubError(f"not a hub URL: {safe_url(url)}") from None
    if port == 0:
        raise HubError(f"not a hub URL: {safe_url(url)}")
    if parts.username or parts.password:
        raise HubError("refusing a URL with credentials in it")
    if parts.scheme not in ("https", "http") or not parts.hostname:
        raise HubError(f"not a hub URL: {safe_url(url)}")
    if parts.scheme == "http" and parts.hostname not in LOOPBACK_HOSTS:
        raise HubError(f"refusing plain HTTP to {parts.hostname}; the hub must be served over TLS")
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, "", "", "")).rstrip("/")


def join_target(url: str) -> str:
    """Where `maity join` sends the exchange, from the URL's shape (docs/api.md §13): a
    `/join/<token>`, `/j/<token>` or `/api/v1/join/<token>` URL → `POST /api/v1/join/<token>` on
    that host; a
    URL whose path is one segment (a join host, §1.1) → `POST` to that same URL."""
    base = hub_base(url)
    path = urllib.parse.urlsplit(url.strip()).path.rstrip("/")
    for prefix in ("/join/", "/j/", f"{API}/join/"):
        token = path[len(prefix) :]
        if path.startswith(prefix) and token and "/" not in token:
            return f"{base}{API}/join/{segment(urllib.parse.unquote(token))}"
    token = path[1:]
    if token and "/" not in token and token not in ("j", "join", "r", "api"):  # a truncated hub URL
        return f"{base}/{segment(urllib.parse.unquote(token))}"
    raise HubError(
        f"not a join URL (expected https://<hub>/join/<token> or https://<join host>/<token>): "
        f"{safe_url(url)}"
    )


def accept_hub(given: str, header: str | None) -> str:
    """The hub's base URL after an exchange: the `Maity-Hub` header (the URL the command was
    given when it is missing), only under the transport rule and only on the host of the
    given URL or that host's parent domain (§13). Anything else is refused before the
    command keeps anything."""
    base = hub_base(given)
    if not header:
        return base
    try:
        claimed = hub_base(header)
    except HubError as exc:
        raise HubError(
            f"the exchange named a hub URL the CLI refuses ({exc}); nothing was stored. The "
            "code is used: ask for a new one"
        ) from None
    host, other = _host(base), _host(claimed)
    if (
        other is None
        or host is None
        or not (other == host or (not _is_address(other) and other == _parent(host)))
    ):
        raise HubError(
            f"the exchange on {host} named {safe_url(claimed)} as the hub, which is neither "
            "that host nor its parent domain; nothing was stored. The code is used: ask for a "
            "new one"
        )
    # Stored the way it is compared: lowercase, IDNA-encoded, no trailing dot.
    parts = urllib.parse.urlsplit(claimed)
    shown = f"[{other}]" if ":" in other else other
    return f"{parts.scheme}://{shown}" + (f":{parts.port}" if parts.port else "")


def _host(url: str) -> str | None:
    """The URL's host for comparison: lowercased, one trailing dot dropped, IDNA-encoded (so
    `。` and the other full stops split labels the way DNS does). None when it cannot be."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host.endswith("."):
        host = host[:-1]
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    try:
        encoded = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        return None
    return encoded if encoded and ".." not in encoded and not encoded.endswith(".") else None


def _is_address(host: str) -> bool:
    """An IP literal, or a name the resolver would read as one (`0.0.1`, `0x7f.1`): no
    top-level domain is numeric."""
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        last = host.rsplit(".", 1)[-1]
        return last.isdigit() or last.startswith("0x")


def _parent(host: str) -> str | None:
    """The direct parent domain while it still has two labels; None for an address."""
    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass
    parent = host.split(".", 1)[1] if "." in host else ""
    return parent if "." in parent else None


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
    details = details if isinstance(details, dict) else {}
    text = f"{what}: {code or 'error'}: {message}"
    if code == "invalid":
        text += _field_reasons(details.get("fields"))
    err = HubError(text, code=code, status=exc.code)
    err.details = details
    retry_after = exc.headers.get("Retry-After") if exc.headers else None
    if retry_after and retry_after.strip().isdigit():
        err.retry_after = float(retry_after.strip())
    return err


_TOKEN = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")


def _field_reasons(fields: Any) -> str:
    """`details.fields` of an `invalid` answer as `field: reason` lines.

    Only field names and reason codes are printed. The hub's reasons are codes such as
    `not_a_member`; anything that is not shaped like one could be a value echoed back and is
    replaced, so no value reaches the agent's context through an error message.
    """
    if not isinstance(fields, dict):
        return ""
    lines = []
    for name, reason in fields.items():
        name = name if _TOKEN.match(str(name)) else "(field)"
        if not (isinstance(reason, str) and _TOKEN.match(reason)):
            reason = "(reason not shown)"
        lines.append(f"\n  {name}: {reason}")
    return "".join(lines)


def _guard_payload(body: bytes, query: str, path: str = "") -> None:
    """Refuse locally what the hub would refuse and, for a real credential, revoke it for.

    The path counts too: an id typed by the agent lands there, and the hub logs it and echoes
    it back in its errors.
    """
    parts = (body.decode("utf-8", errors="replace"), urllib.parse.unquote(query))
    if any(sign.contains_credential(p) for p in (*parts, urllib.parse.unquote(path))):
        raise HubError(
            "refusing to send: the request contains a string in the credential format "
            "(mty1.<id>.<secret>); remove it — the hub would revoke a real one"
        )


def get_text(url: str, timeout: float = 30.0) -> str:
    """GET `url`, which callers build from `hub_base()`, so its scheme is http(s) only."""
    headers = {"Accept": "text/markdown, text/plain", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    try:
        with opener().open(request, timeout=timeout) as response:
            body: bytes = response.read()
            charset = response.headers.get_content_charset() or "utf-8"
            return body.decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise _error_from(exc, safe_url(url)) from exc
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


def _exchange(
    url: str, code: str, what: str, timeout: float, client: str = CLIENT
) -> tuple[Secret, Message]:
    """POST a single-use code to an exchange whose answer body is a credential and nothing
    else (§3.3, §15.2). The body is checked for the credential format and handed back as a
    `Secret`; it is never decoded into anything that could be printed, and an error body is
    never mistaken for it."""
    body = json.dumps({"code": code, "client": client}).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    request = urllib.request.Request(url, data=body, method="POST", headers=headers)  # noqa: S310
    try:
        with opener().open(request, timeout=timeout) as response:
            raw: bytes = response.read()
            facts: Message = response.headers
    except urllib.error.HTTPError as exc:
        raise _error_from(exc, what) from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise HubError(f"cannot reach {safe_url(url)}: {getattr(exc, 'reason', exc)}") from exc
    value = raw.decode("utf-8", errors="replace").strip()
    if not sign.is_credential(value):
        raise HubError(f"the {what} exchange answered with something that is not a credential")
    return Secret(value), facts


def exchange(url: str, code: str, timeout: float = 30.0, client: str = CLIENT) -> JoinResult:
    """The join exchange (§3.3) at `url`, from `join_target()`."""
    credential, facts = _exchange(url, code, "join", timeout, client)
    return JoinResult(
        credential=credential,
        credential_id=facts.get("Maity-Credential-Id"),
        member_id=facts.get("Maity-Member-Id"),
        project=facts.get("Maity-Project"),
        hub=facts.get("Maity-Hub"),
    )


def pair_token(url: str) -> str:
    """The token from `https://<hub>/r/<token>` or `https://<hub>/api/v1/runners/pair/<token>`."""
    path = urllib.parse.urlsplit(url.strip()).path.rstrip("/")
    for prefix in ("/r/", f"{API}/runners/pair/"):
        if path.startswith(prefix) and "/" not in path[len(prefix) :] and path[len(prefix) :]:
            return urllib.parse.unquote(path[len(prefix) :])
    raise HubError(f"not a pairing URL (expected /r/<token>): {safe_url(url)}")


@dataclass(frozen=True)
class PairResult:
    credential: Secret
    credential_id: str | None
    runner_id: str | None
    attached: list[str]
    hub: str | None


def pair_exchange(base: str, token: str, code: str, timeout: float = 30.0) -> PairResult:
    """POST /runners/pair/{token} (§15.2): the runner's credential, and the projects attached."""
    url = f"{base}{API}/runners/pair/{segment(token)}"
    credential, facts = _exchange(url, code, "pairing", timeout)
    attached = [s.strip() for s in (facts.get("Maity-Attached") or "").split(",") if s.strip()]
    return PairResult(
        credential=credential,
        credential_id=facts.get("Maity-Credential-Id"),
        runner_id=facts.get("Maity-Runner-Id"),
        attached=attached,
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
    _opener: urllib.request.OpenerDirector = field(default_factory=opener, repr=False)

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
        if "#" in path:
            raise HubError(f"a path has no fragment: {path!r}")
        path, _, inline_query = path.partition("?")
        if inline_query:
            # `/events?after=28` is signed with the pairs in the canonical query, as --query
            # would put them, not with the `?` inside the signed path (§2.2).
            query = [*urllib.parse.parse_qsl(inline_query, keep_blank_values=True), *query]
        full_path = path if path.startswith(f"{API}/") else f"{API}{path}"
        query_string = sign.canonical_query(query)
        data = b"" if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        _guard_payload(data, query_string, path)
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
