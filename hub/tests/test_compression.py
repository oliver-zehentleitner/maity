"""Responses gzipped where the client asks for it (hub/src/maity_hub/compression.py)."""

from __future__ import annotations

import asyncio
import gzip
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from starlette.types import Message, Receive, Scope, Send

from maity_hub.compression import MINIMUM_SIZE, Compression
from tests import flow
from tests.conftest import ClientFactory

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


def test_a_join_document_carrying_its_token_is_never_gzipped(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner)
    token = flow.join(owner, "maity")["join_url"].rsplit("/", 1)[1]
    for accept in ("text/markdown", "text/html"):
        page = make_client().get(f"/api/v1/join/{token}", headers={"Accept": accept, **GZIP})
        assert page.status_code == 200 and token in page.text, accept
        assert len(page.content) >= MINIMUM_SIZE, accept  # large enough to be gzipped otherwise
        assert "content-encoding" not in page.headers, accept


def test_without_accept_encoding_nothing_is_gzipped(client: TestClient) -> None:
    done = client.get("/api/v1/openapi.json", headers={"Accept-Encoding": "identity"})
    assert done.status_code == 200 and "content-encoding" not in done.headers


async def _answer(scope: Scope, receive: Receive, send: Send) -> None:
    body = b"x" * (MINIMUM_SIZE * 4)
    kinds = {".png": b"image/png", ".zip": b"application/zip"}
    kind = next((v for k, v in kinds.items() if scope["path"].endswith(k)), b"application/json")
    await send({"type": "http.response.start", "status": 200,
                "headers": [(b"content-type", kind),
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
        ("GET", "/api/v1/join/abcdefghijklmnopqrstuv", None),
        ("GET", "/api/v1/invitations/abcdefghijklmnopqrstuv", None),
        ("GET", "/api/v1/projects/o/p/invitations", "gzip"),
        ("GET", "/join/abc", None),
        ("GET", "/r/abc", None),
        ("GET", "/mail/abc", None),
        ("GET", "/api/v1/projects/o/p/attachments/att-1/content", None),
        ("GET", "/api/v1/projects/o/p/attachments/att-1", "gzip"),
        ("GET", "/api/v1/avatars/agt-1/picture.png", None),
        ("GET", "/assets/brand/mark.png", None),
        ("GET", "/api/v1/me/export/archive.zip", None),
        ("GET", "/", None),
        ("GET", "/oliver/maity/board", None),
        ("GET", "/abcdefghijklmnopqrstuv", None),
    ],
)
def test_only_reads_of_the_api_and_the_files_are_gzipped_never_auth(
    method: str, path: str, expected: str | None
) -> None:
    assert asyncio.run(_encoding(method, path)) == expected
