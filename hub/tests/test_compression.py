"""Responses gzipped where the client asks for it (hub/src/maity_hub/compression.py)."""

from __future__ import annotations

import asyncio
import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.types import Message, Receive, Scope, Send

from maity_hub.compression import MINIMUM_SIZE, Compression

GZIP = {"Accept-Encoding": "gzip"}


def test_a_large_read_is_gzipped_with_vary(client: TestClient) -> None:
    done = client.get("/api/v1/openapi.json", headers=GZIP)
    assert done.status_code == 200
    assert done.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in done.headers["vary"].lower()
    assert done.json()["openapi"]


def test_the_dashboard_files_are_gzipped(client: TestClient, web_dir: Path) -> None:
    (web_dir / "js").mkdir()
    (web_dir / "js" / "app.js").write_text("// the dashboard\n" * 400)
    done = client.get("/assets/js/app.js", headers=GZIP)
    assert done.status_code == 200 and done.headers["content-encoding"] == "gzip"
    assert done.text == "// the dashboard\n" * 400


def test_without_accept_encoding_nothing_is_gzipped(client: TestClient) -> None:
    done = client.get("/api/v1/openapi.json", headers={"Accept-Encoding": "identity"})
    assert done.status_code == 200 and "content-encoding" not in done.headers


async def _answer(scope: Scope, receive: Receive, send: Send) -> None:
    body = b"x" * (MINIMUM_SIZE * 4)
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", b"application/json"),
                            (b"content-length", str(len(body)).encode())]})  # fmt: skip
    await send({"type": "http.response.body", "body": body})


async def _encoding(method: str, path: str) -> str | None:
    sent: list[Message] = []

    async def receive() -> Message:
        return {"type": "http.request", "body": b""}

    async def send(message: Message) -> None:
        sent.append(message)

    scope: Scope = {"type": "http", "method": method, "path": path,
                    "headers": [(b"accept-encoding", b"gzip")]}  # fmt: skip
    await Compression(_answer)(scope, receive, send)
    headers = dict(sent[0]["headers"])
    encoding = headers.get(b"content-encoding")
    if encoding == b"gzip":
        assert gzip.decompress(b"".join(m.get("body", b"") for m in sent[1:])) == b"x" * (
            MINIMUM_SIZE * 4
        )
    return encoding.decode() if encoding else None


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("GET", "/api/v1/projects/o/p/tasks", "gzip"),
        ("GET", "/assets/js/app.js", "gzip"),
        ("HEAD", "/api/v1/projects/o/p/tasks", "gzip"),
        ("POST", "/api/v1/projects/o/p/tasks", None),
        ("PATCH", "/api/v1/me", None),
        ("GET", "/api/v1/auth/session", None),
        ("GET", "/api/v1/auth/sessions", None),
        ("GET", "/join/abc", None),
        ("GET", "/r/abc", None),
        ("GET", "/mail/abc", None),
        ("GET", "/api/v1/projects/o/p/attachments/att-1/content", None),
        ("GET", "/api/v1/projects/o/p/attachments/att-1", "gzip"),
        ("GET", "/", None),
        ("GET", "/oliver/maity/board", None),
        ("GET", "/abcdefghijklmnopqrstuv", None),
    ],
)
def test_only_reads_of_the_api_and_the_files_are_gzipped_never_auth(
    method: str, path: str, expected: str | None
) -> None:
    assert asyncio.run(_encoding(method, path)) == expected
