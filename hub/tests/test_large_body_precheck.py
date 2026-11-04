"""A body above the default cap is read only for a caller the headers may authenticate (§1.7):
the attachment upload (test_attachments.py), and here the images and the landing, legal and
sign-in pages' settings and their previews."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from fastapi.routing import iter_route_contexts
from sqlalchemy import Engine

from maity_hub import middleware
from maity_hub.app import create_app
from maity_hub.config import Settings
from tests import flow
from tests.conftest import ClientFactory

# Every route whose body may be larger than the default 64 KiB, but the attachment upload.
LARGE = [
    ("PUT", "/api/v1/projects/maintainer/maity/logo"),
    ("PUT", "/api/v1/projects/maintainer/maity/banner"),
    ("PUT", "/api/v1/me/avatar"),
    ("PUT", "/api/v1/agents/agt-nobody/avatar"),
    ("PUT", "/api/v1/orgs/acme/avatar"),
    ("PATCH", "/api/v1/admin/settings/landing"),
    ("PATCH", "/api/v1/admin/settings/legal"),
    ("PATCH", "/api/v1/admin/settings/auth-pages"),
    ("POST", "/api/v1/admin/settings/landing/preview"),
    ("POST", "/api/v1/admin/settings/legal/preview"),
    ("POST", "/api/v1/admin/settings/auth-pages/check"),
]
SIZE = 100 * 1024  # above the default cap, below every cap of these routes


def _drive(
    client: Any,
    method: str,
    path: str,
    headers: list[tuple[bytes, bytes]],
    query: bytes = b"",
    size: int = SIZE,
    host: bytes = b"hub.example",
) -> tuple[int, str, int]:
    """The request driven at the hub itself: its status, `Maity-Error` and how often the
    hub asked for the body."""
    asked = [0]

    async def receive() -> dict[str, object]:
        asked[0] += 1
        return {"type": "http.request", "body": b"", "more_body": False}

    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http", "http_version": "1.1", "method": method, "scheme": "https",
        "path": path, "raw_path": path.encode(), "root_path": "",
        "query_string": query, "server": ("hub.example", 443),
        "client": ("203.0.113.7", 1),
        "headers": [
            (b"host", host),
            (b"content-type", b"application/json"),
            (b"content-length", str(size).encode()),
            *headers,
        ],
    }  # fmt: skip
    asyncio.run(client.app(scope, receive, send))
    start = sent[0]
    error = dict(start["headers"]).get(b"maity-error", b"").decode()
    return start["status"], error, asked[0]


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def test_every_large_body_route_is_one_the_pre_check_covers() -> None:
    for method, path in LARGE:
        assert middleware._body_cap({"method": method, "path": path})[0] > middleware.BODY_CAP
    assert middleware._body_cap({"method": "POST", "path": "/api/v1/me"})[0] == middleware.BODY_CAP


def test_large_names_every_route_of_the_app_with_a_large_body(
    settings: Settings, migrated: Engine
) -> None:
    # Walked from the router, each parameter filled with a name: the list above is complete.
    large = set()
    for route in iter_route_contexts(list(create_app(settings, migrated).routes)):
        for method in route.methods or ():
            path = re.sub(r"\{[^}]+\}", "x", route.path or "")
            if middleware._body_cap({"method": method, "path": path})[0] > middleware.BODY_CAP:
                large.add((method, path))
    upload = ("POST", "/api/v1/projects/x/x/attachments")  # test_attachments.py
    named = {(m, re.sub(r"/(maintainer|maity|agt-nobody|acme)(?=/)", "/x", p)) for m, p in LARGE}
    assert large == named | {upload}


@pytest.mark.parametrize(("method", "path"), LARGE)
@pytest.mark.parametrize(
    "headers",
    [
        [],
        [(b"authorization", b"Bearer mty1.crd-nobody.AAAA")],
        [(b"authorization", b"Basic eDp5")],
        [(b"cookie", b"maity_session=ended")],
    ],
)
def test_a_large_body_no_caller_could_send_is_refused_unread(
    owner: flow.Human, method: str, path: str, headers: list[tuple[bytes, bytes]]
) -> None:
    assert _drive(owner.client, method, path, headers) == (401, "unauthenticated", 0)


@pytest.mark.parametrize(("method", "path"), LARGE)
def test_a_credential_in_the_query_of_a_large_body_route_is_revoked_unread(
    owner: flow.Human, make_client: ClientFactory, method: str, path: str
) -> None:
    agent = flow.agent(make_client, owner)
    query = f"x={agent.credential}".encode()
    assert _drive(owner.client, method, path, [], query) == (400, "credential_in_payload", 0)
    assert agent.get("/me").status_code == 401  # revoked


def test_a_caller_the_headers_authenticate_has_the_body_read(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    agent = flow.agent(make_client, owner)
    headers = [(b"authorization", f"Bearer {agent.credential}".encode())]
    status, _, asked = _drive(owner.client, "PUT", "/api/v1/me/avatar", headers)
    assert asked == 1 and status != 401


def test_a_body_under_the_default_cap_is_read_before_the_caller_is_known(
    owner: flow.Human,
) -> None:
    # Only a large body waits for the headers; a small one is read and scanned first (§2.2).
    status, code, asked = _drive(owner.client, "PATCH", "/api/v1/me", [], size=1024)
    assert (status, code) == (401, "unauthenticated") and asked == 1


@pytest.mark.parametrize(
    ("method", "path"), [*LARGE, ("POST", "/api/v1/projects/maintainer/maity/attachments")]
)
def test_on_the_join_host_a_large_body_is_refused_unread(
    make_client: ClientFactory, migrated: Engine, method: str, path: str
) -> None:
    # Only the join is served there, and it takes no large body: every body is held to the
    # default cap, whatever the same path takes on the public host.
    client = make_client(base_url="https://join.example", join_url="https://join.example")
    status, code, asked = _drive(client, method, path, [], host=b"join.example")
    assert (status, code, asked) == (413, "payload_too_large", 0)
