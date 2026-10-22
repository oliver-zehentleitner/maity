"""A hub on loopback that speaks just enough of docs/api.md to test the CLI against.

It verifies signatures with its own implementation of §2.2, written from the document rather
than imported from `maity.sign`, so a mistake in one is not mirrored by the other.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SECRET = "yq3Zt0kQ2vXy9aBcDeFgHiJkLmNoPqRsTuVwXyZ0123"
CREDENTIAL_ID = "crd-b-0003"
CREDENTIAL = f"mty1.{CREDENTIAL_ID}.{SECRET}"
TOKEN = "9fK2tok"
CODE = "Q7MD-3XPL-8ZWE"
VERIFIER = hashlib.sha256(SECRET.encode()).digest()
RUNNER_CREDENTIAL_ID = "rcrd-0002-0001"
RUNNER_CREDENTIAL = f"mty1.{RUNNER_CREDENTIAL_ID}.{SECRET}"
PAIR_TOKEN = "Xb7pairtok"
PAIR_CODE = "K3PF-9QZD-1MWA"


def canonical_query(raw_query: str) -> str:
    """The hub's rule: split on '&' and the first '=', percent-decode ('+' stays '+', unlike
    parse_qsl), re-encode with safe '-_.~', sort bytewise by the encoded key, keep repeats."""

    def enc(text: str) -> str:
        return urllib.parse.quote(urllib.parse.unquote(text), safe="-_.~")

    pairs = [p.partition("=") for p in raw_query.split("&") if p]
    encoded = [(enc(k), enc(v)) for k, _, v in pairs]
    encoded.sort(key=lambda kv: kv[0])
    return "&".join(f"{k}={v}" for k, v in encoded)


def canonical(method: str, raw_path: str, raw_query: str, ts: str, nonce: str, body: bytes) -> str:
    query = canonical_query(raw_query)
    return "\n".join(
        ["MAITY-HMAC-V1", method, raw_path, query, ts, nonce, hashlib.sha256(body).hexdigest()]
    )


@dataclass
class Seen:
    method: str
    path: str
    query: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        return json.loads(self.body)


@dataclass
class FakeHub:
    url: str = ""
    seen: list[Seen] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    skew_once: bool = False
    join_used: bool = False
    pair_used: bool = False
    hub_header: str | None = None  # Maity-Hub answered by the exchanges; None: the hub's URL
    # (method, path) -> (status, payload) or (status, payload, headers)
    routes: dict[tuple[str, str], Callable[[Seen], tuple[Any, ...]]] = field(default_factory=dict)
    redirects: dict[str, str] = field(default_factory=dict)

    def signed(self) -> list[Seen]:
        return [s for s in self.seen if s.headers.get("authorization", "").startswith("Maity-HMAC")]


def _handler(hub: FakeHub) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args: Any) -> None:
            pass

        def _send(self, status: int, payload: Any, headers: dict[str, str] | None = None) -> None:
            if isinstance(payload, bytes | str):
                data = payload.encode() if isinstance(payload, str) else payload
                ctype = "text/plain; charset=utf-8"
            else:
                data = json.dumps(payload).encode()
                ctype = "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            if status >= 400 and isinstance(payload, dict):
                self.send_header("Maity-Error", payload["error"]["code"])
            self.end_headers()
            self.wfile.write(data)

        def _error(self, status: int, code: str, details: dict[str, Any] | None = None) -> None:
            self._send(status, {"error": {"code": code, "message": code, "details": details or {}}})

        def _verify(self, seen: Seen) -> bool:
            auth = seen.headers.get("authorization", "")
            if auth not in (f"Maity-HMAC {CREDENTIAL_ID}", f"Maity-HMAC {RUNNER_CREDENTIAL_ID}"):
                self._error(401, "unauthenticated")
                return False
            if hub.skew_once:
                hub.skew_once = False
                self._error(401, "timestamp_skew", {"server_time": "2099-01-01T00:00:00Z"})
                return False
            text = canonical(
                seen.method,
                seen.path,
                seen.query,
                seen.headers["maity-timestamp"],
                seen.headers["maity-nonce"],
                seen.body,
            )
            expected = hmac.new(VERIFIER, text.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, seen.headers.get("maity-signature", "")):
                self._error(401, "signature_invalid")
                return False
            exempt = seen.path == "/api/v1/me/resume" or seen.path.startswith(
                ("/api/v1/runner/hello", "/api/v1/runner/placements/")
            )
            if seen.method in ("POST", "PATCH") and not exempt:
                if not 16 <= len(seen.headers.get("idempotency-key", "")) <= 128:
                    self._error(400, "invalid", {"fields": {"Idempotency-Key": "required"}})
                    return False
            return True

        def _handle(self) -> None:
            path, _, query = self.path.partition("?")
            length = int(self.headers.get("Content-Length") or 0)
            seen = Seen(
                self.command,
                path,
                query,
                {k.lower(): v for k, v in self.headers.items()},
                self.rfile.read(length),
            )
            hub.seen.append(seen)
            if path in hub.redirects:
                self.send_response(302)
                self.send_header("Location", hub.redirects[path])
                self.send_header("Content-Length", "0")
                self.end_headers()
                return None
            if path == "/api/v1/help":
                return self._send(200, "# Maity help\n")
            if path == "/api/v1/health":
                return self._send(200, {"status": "ok"})
            if path == f"/api/v1/runners/pair/{PAIR_TOKEN}" and self.command == "POST":
                if hub.pair_used:
                    return self._error(404, "not_found")
                if seen.json().get("code") != PAIR_CODE:
                    return self._error(403, "code_invalid")
                hub.pair_used = True
                return self._send(
                    201,
                    RUNNER_CREDENTIAL,
                    {
                        "Maity-Credential-Id": RUNNER_CREDENTIAL_ID,
                        "Maity-Runner-Id": "rnr-0002",
                        "Maity-Attached": "maity, sample",
                        "Maity-Hub": hub.hub_header or hub.url,
                        "Maity-Signing": "required",
                    },
                )
            if path in (f"/api/v1/join/{TOKEN}", f"/{TOKEN}") and self.command == "POST":
                if hub.join_used:
                    return self._error(404, "not_found")
                if seen.json().get("code") != CODE:
                    return self._error(403, "code_invalid")
                hub.join_used = True
                return self._send(
                    201,
                    CREDENTIAL,
                    {
                        "Maity-Credential-Id": CREDENTIAL_ID,
                        "Maity-Member-Id": "agt-b",
                        "Maity-Project": "maity",
                        "Maity-Hub": hub.hub_header or hub.url,
                    },
                )
            if not self._verify(seen):
                return None
            route = hub.routes.get((self.command, path))
            if route is not None:
                status, payload, *extra = route(seen)
                return self._send(status, payload, *extra)
            if path == "/api/v1/me/resume":
                return self._send(
                    200,
                    {
                        "session": {"id": "ses-b-0004"},
                        "hints": {"wait_timeout": 120},
                        "events": {"after": 0, "items": [], "cursor": 4231},
                        "me": {"member_id": "agt-b", "owner": {"id": "hum-1", "handle": "m"}},
                    },
                )
            if path == "/api/v1/projects/maity/events":
                after = int(dict(urllib.parse.parse_qsl(query)).get("after", "0"))
                items = [e for e in hub.events if e["seq"] > after]
                if not items and "wait=" in query:
                    time.sleep(0.2)
                cursor = items[-1]["seq"] if items else after
                return self._send(200, {"items": items, "cursor": cursor, "superseded": False})
            return self._error(404, "not_found")

        do_GET = do_POST = do_PATCH = do_PUT = do_DELETE = _handle

    return Handler


def serve() -> Iterator[FakeHub]:
    hub = FakeHub()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(hub))
    hub.url = f"http://127.0.0.1:{server.server_address[1]}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield hub
    finally:
        server.shutdown()
        server.server_close()
