"""docs/api.md §2.3 "The proxy", §7: the owner's go on one governance call of a proxy."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from tests import factory, flow
from tests.conftest import ClientFactory

PROJECT = "/projects/maintainer/maity"
API = "/api/v1"
TICKER = f"{PROJECT}/ticker"
ITEM = json.dumps({"text": "A release is out", "type": "note", "areas": ["hub/"]})


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    human = flow.human(make_client, migrated)
    flow.project(human)
    return human


def _project(engine: Engine) -> str:
    with engine.connect() as conn:
        found: str = conn.execute(select(t.project.c.id)).scalar_one()
    return found


class Proxy:
    """An agent's signed calls, as the CLI sends them (§2.2)."""

    def __init__(self, client: Any, agent: factory.Agent) -> None:
        self.client, self.agent = client, agent

    def call(
        self,
        method: str,
        path: str,
        body: str | None = None,
        *,
        on_request: str | None = None,
        signed_as: str | None = None,
    ) -> Any:
        raw = body.encode() if body is not None else b""
        full = f"{API}{path}"
        stamp, nonce = str(int(clock.now().timestamp())), secrets.token_urlsafe(16)
        target, _, query = full.partition("?")
        canonical = credentials.canonical_string(
            method,
            target.encode(),
            query.encode(),
            stamp,
            nonce,
            raw,
            on_request=signed_as or on_request,
        )
        key = hashlib.sha256(self.agent.value.split(".")[2].encode()).digest()
        headers = {
            "Authorization": f"Maity-HMAC {self.agent.credential_id}",
            "Maity-Timestamp": stamp,
            "Maity-Nonce": nonce,
            "Maity-Signature": hmac.new(key, canonical.encode(), "sha256").hexdigest(),
            "Idempotency-Key": secrets.token_urlsafe(16),
            "Content-Type": "application/json",
        }
        if on_request is not None:
            headers["Maity-On-Request"] = on_request
        return self.client.request(method, full, content=raw, headers=headers)

    def ask(self, action: dict[str, Any] | None = None, **body: Any) -> Any:
        wanted = {
            "class": "decision",
            "title": "Post this?",
            "to": "owner",
            "action": action or {"method": "POST", "path": TICKER, "query": None, "body": ITEM},
            **body,
        }
        return self.call("POST", f"{PROJECT}/requests", json.dumps(wanted))


@pytest.fixture
def proxy(owner: flow.Human, make_client: ClientFactory, migrated: Engine) -> Proxy:
    agent = factory.agent(migrated, _project(migrated), owner.id, "proxy", instance="prx1")
    return Proxy(make_client(), agent)


def _go(owner: flow.Human, proxy: Proxy, reply: str = "go", **action: Any) -> str:
    asked = proxy.ask(action or None)
    assert asked.status_code == 201, asked.text
    request_id: str = asked.json()["id"]
    answered = owner.post(f"{PROJECT}/requests/{request_id}/answer", {"reply_id": reply})
    assert answered.status_code == 200, answered.text
    return request_id


def _refused(response: Any, on_request: str) -> None:
    assert response.status_code == 403, response.text
    details = response.json()["error"]["details"]
    assert details["reason"] == "proxy_needs_decision"
    assert details["on_request"] == on_request


def test_the_request_shows_the_call_its_hash_and_go_and_no(owner: flow.Human, proxy: Proxy) -> None:
    view = proxy.ask().json()
    assert view["action"] == {
        "method": "POST",
        "path": TICKER,
        "query": None,
        "body": ITEM,
        "body_sha256": hashlib.sha256(ITEM.encode()).hexdigest(),
        "used_at": None,
        "used_seq": None,
    }
    assert [r["id"] for r in view["replies"]] == ["go", "no"]
    plain = owner.post(f"{PROJECT}/requests", {"class": "info", "title": "Hm", "to": "owner"})
    assert plain.json()["action"] is None


@pytest.mark.parametrize(
    ("body", "field", "value"),
    [
        ({"class": "info"}, "action", "class"),
        ({"to": "trust:admin"}, "action", "to"),
        ({"options": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}]}, "action", "options"),
    ],
)
def test_only_on_a_decision_or_consent_to_the_owner_without_options(
    proxy: Proxy, body: dict[str, Any], field: str, value: str
) -> None:
    refused = proxy.ask(**body)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"][field] == value


@pytest.mark.parametrize(
    ("change", "field", "value"),
    [
        ({"body": "not json"}, "action.body", "not_json"),
        ({"method": "GET"}, "action.method", "unknown"),
        ({"path": "no-slash"}, "action.path", "not_a_path"),
    ],
)
def test_the_call_is_checked(proxy: Proxy, change: dict[str, Any], field: str, value: str) -> None:
    action = {"method": "POST", "path": TICKER, "query": None, "body": None, **change}
    refused = proxy.ask(action)
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"][field] == value


def test_a_body_at_the_cap_does_not_fit_its_request_yet(proxy: Proxy) -> None:
    """The whole request is capped at 64 KiB (§1.7), so `too_large` stays out of reach for now:
    the hub refuses first, with the wrapper counted."""
    action = {"method": "POST", "path": TICKER, "body": json.dumps("x" * 65536)}
    assert proxy.ask(action).status_code == 413


def test_only_a_proxy_sets_action(owner: flow.Human, make_client: ClientFactory) -> None:
    refused = owner.post(
        f"{PROJECT}/requests",
        {
            "class": "decision",
            "title": "Post this?",
            "to": "owner",
            "action": {"method": "POST", "path": TICKER},
        },
    )
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"]["action"] == "proxy_only"


def test_a_signature_without_the_header_line_does_not_verify(proxy: Proxy) -> None:
    refused = proxy.call("POST", TICKER, ITEM, on_request="req-a", signed_as="req-b")
    assert refused.headers["Maity-Error"] == "signature_invalid"


def test_a_go_opens_exactly_one_call_and_records_it(
    owner: flow.Human, proxy: Proxy, migrated: Engine
) -> None:
    request_id = _go(owner, proxy, method="POST", path=TICKER, query=None, body=ITEM)
    done = proxy.call("POST", TICKER, ITEM, on_request=request_id)
    assert done.status_code == 201, done.text
    action = owner.get(f"{PROJECT}/requests/{request_id}").json()["action"]
    assert action["used_at"] is not None
    with migrated.connect() as conn:
        event = conn.execute(select(t.event).where(t.event.c.seq == action["used_seq"])).one()
    assert event.kind == "request_action_used"
    assert event.payload["id"] == request_id
    _refused(proxy.call("POST", TICKER, ITEM, on_request=request_id), "used")


def test_without_the_header_the_call_is_refused_and_coder_scopes_need_none(proxy: Proxy) -> None:
    _refused(proxy.call("POST", TICKER, ITEM), "missing")
    assert proxy.call("GET", f"{PROJECT}/requests").status_code == 200


def test_an_open_or_refused_or_foreign_request_opens_nothing(
    owner: flow.Human, proxy: Proxy, make_client: ClientFactory, migrated: Engine
) -> None:
    opened = proxy.ask().json()["id"]
    _refused(proxy.call("POST", TICKER, ITEM, on_request=opened), "unanswered")
    declined = _go(owner, proxy, "no")
    _refused(proxy.call("POST", TICKER, ITEM, on_request=declined), "declined")
    _refused(proxy.call("POST", TICKER, ITEM, on_request="req-none"), "not_bound")
    other = factory.agent(migrated, _project(migrated), owner.id, "proxy", instance="prx2")
    theirs = _go(owner, Proxy(make_client(), other))
    _refused(proxy.call("POST", TICKER, ITEM, on_request=theirs), "not_bound")


def test_a_go_is_bound_to_the_method_path_query_and_body_and_stays_unused(
    owner: flow.Human, proxy: Proxy
) -> None:
    request_id = _go(owner, proxy, method="POST", path=TICKER, query=None, body=ITEM)
    changed = json.dumps({"text": "Another text", "type": "note", "areas": ["hub/"]})
    _refused(proxy.call("POST", TICKER, changed, on_request=request_id), "mismatch")
    _refused(proxy.call("POST", f"{TICKER}?a=1", ITEM, on_request=request_id), "mismatch")
    assert proxy.call("POST", TICKER, ITEM, on_request=request_id).status_code == 201


def test_two_calls_racing_on_one_go_succeed_at_most_once(owner: flow.Human, proxy: Proxy) -> None:
    request_id = _go(owner, proxy, method="POST", path=TICKER, query=None, body=ITEM)
    with ThreadPoolExecutor(2) as pool:
        calls = [
            pool.submit(proxy.call, "POST", TICKER, ITEM, on_request=request_id) for _ in range(2)
        ]
    assert sorted(call.result().status_code for call in calls) == [201, 403]


def test_a_go_expires_after_24_hours(owner: flow.Human, proxy: Proxy, migrated: Engine) -> None:
    request_id = _go(owner, proxy, method="POST", path=TICKER, query=None, body=ITEM)
    with migrated.begin() as conn:
        conn.execute(
            update(t.request)
            .where(t.request.c.id == request_id)
            .values(answered_at=clock.now() - timedelta(hours=24, seconds=1))
        )
    _refused(proxy.call("POST", TICKER, ITEM, on_request=request_id), "expired")


def test_a_call_that_fails_leaves_the_go_unused(owner: flow.Human, proxy: Proxy) -> None:
    bad = json.dumps({"text": "x", "type": "not-a-type"})
    request_id = _go(owner, proxy, method="POST", path=TICKER, query=None, body=bad)
    failed = proxy.call("POST", TICKER, bad, on_request=request_id)
    assert failed.status_code >= 400 and failed.status_code != 403, failed.text
    action = owner.get(f"{PROJECT}/requests/{request_id}").json()["action"]
    assert action["used_at"] is None and action["used_seq"] is None


def test_a_human_only_scope_stays_closed_to_an_agent_proxy(owner: flow.Human, proxy: Proxy) -> None:
    path = f"{PROJECT}"
    body = json.dumps({"name": "New name"})
    request_id = _go(owner, proxy, method="PATCH", path=path, query=None, body=body)
    refused = proxy.call("PATCH", path, body, on_request=request_id)
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"].get("reason") != "proxy_needs_decision"


def test_only_the_owner_answers_directly(
    owner: flow.Human, proxy: Proxy, make_client: ClientFactory, migrated: Engine
) -> None:
    request_id = proxy.ask().json()["id"]
    admin = flow.human(make_client, migrated, "an-admin")
    factory.membership(migrated, _project(migrated), "coder", trust="admin", human_id=admin.id)
    second = factory.agent(migrated, _project(migrated), owner.id, "proxy", instance="prx3")
    for answering in (
        admin.post(f"{PROJECT}/requests/{request_id}/answer", {"reply_id": "go"}),
        Proxy(make_client(), second).call(
            "POST", f"{PROJECT}/requests/{request_id}/answer", json.dumps({"reply_id": "go"})
        ),
    ):
        assert answering.status_code == 403, answering.text
        assert answering.json()["error"]["details"]["reason"] == "action_needs_owner"
