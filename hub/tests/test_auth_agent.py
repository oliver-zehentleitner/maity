"""docs/api.md §2.2, §2.4, §2.5: agent credentials, side effects, forwarded headers."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, select, update

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.auth import credentials
from maity_hub.auth.caller import RequestFacts, authenticate
from maity_hub.net import Origin
from tests import factory
from tests.conftest import ClientFactory


@pytest.fixture
def agent(migrated: Engine) -> factory.Agent:
    project_id = factory.project(migrated, "maity")
    owner = factory.human(migrated, "maintainer")
    factory.membership(migrated, project_id, human_id=owner)
    return factory.agent(migrated, project_id, owner)


def bearer(agent: factory.Agent) -> dict[str, str]:
    return {"Authorization": f"Bearer {agent.value}"}


def signed(
    agent: factory.Credentialed,
    method: str,
    path: str,
    query: str = "",
    body: bytes = b"",
    *,
    timestamp: int | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """What the CLI sends, built from the contract's description alone (§2.2)."""
    secret = agent.value.split(".")[2]
    key = hashlib.sha256(secret.encode()).digest()
    timestamp_text = str(timestamp if timestamp is not None else int(clock.now().timestamp()))
    nonce = nonce or secrets.token_urlsafe(16)
    canonical = "\n".join(
        [
            "MAITY-HMAC-V1",
            method,
            path,
            query,
            timestamp_text,
            nonce,
            hashlib.sha256(body).hexdigest(),
        ]
    )
    return {
        "Authorization": f"Maity-HMAC {agent.credential_id}",
        "Maity-Timestamp": timestamp_text,
        "Maity-Nonce": nonce,
        "Maity-Signature": hmac.new(key, canonical.encode(), "sha256").hexdigest(),
    }


# --- bearer ---------------------------------------------------------------------------


def test_bearer_over_tls_answers_the_agents_me(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    response = make_client().get("/api/v1/me", headers=bearer(agent))
    assert response.status_code == 200
    body = response.json()
    assert body["member"] == {
        "id": agent.agent_id,
        "kind": "agent",
        "handle": agent.agent_id,
        "display_name": f"Agent {agent.agent_id}",
        "owner_id": agent.owner_id,
    }
    assert body["projects"] == [
        {"slug": "maity", "name": "Project maity", "state": "build", "role": "member"}
    ]
    assert "open_requests" not in body["projects"][0]


def test_bearer_over_plain_http_off_loopback_is_insecure_transport(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    response = make_client(base_url="http://hub.example").get("/api/v1/me", headers=bearer(agent))
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "insecure_transport"


@pytest.mark.parametrize("peer", ["127.0.0.1", "::1"])
def test_bearer_over_plain_http_on_loopback_is_fine(
    make_client: ClientFactory, agent: factory.Agent, peer: str
) -> None:
    client = make_client(base_url="http://localhost:8080", peer=peer)
    assert client.get("/api/v1/me", headers=bearer(agent)).status_code == 200


def test_plain_http_mode_accepts_bearer_from_anywhere(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client(base_url="http://hub.lan", allow_plain_http=True)
    assert client.get("/api/v1/me", headers=bearer(agent)).status_code == 200


@pytest.mark.parametrize(
    "value",
    [
        "mty1.crd-nobody.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "not-a-credential",
    ],
)
def test_an_unknown_bearer_is_unauthenticated(make_client: ClientFactory, value: str) -> None:
    # Sent in the header, never in a body: the payload filter would refuse it first.
    response = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {value}"})
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "unauthenticated"


def test_a_wrong_secret_is_unauthenticated(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    forged = f"mty1.{agent.credential_id}.{'C' * 43}"
    response = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {forged}"})
    assert response.headers["Maity-Error"] == "unauthenticated"


def test_a_revoked_credential_says_so(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine
) -> None:
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(revoked_at=clock.now(), revoked_reason="by_owner")
        )
    response = make_client().get("/api/v1/me", headers=bearer(agent))
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "credential_revoked"
    assert response.json()["error"]["details"] == {"reason": "by_owner"}


def test_the_header_authenticates_when_a_cookie_is_present_too(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client()
    client.cookies.set("maity_session", "whatever", domain="hub.example")
    response = client.get("/api/v1/me", headers=bearer(agent))
    assert response.json()["member"]["kind"] == "agent"


# --- signed -------------------------------------------------------------------------------


def test_a_signed_request_authenticates_over_plain_http(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client(base_url="http://hub.example")
    response = client.get("/api/v1/me", headers=signed(agent, "GET", "/api/v1/me"))
    assert response.status_code == 200, response.text
    assert response.json()["member"]["id"] == agent.agent_id


def test_the_signature_covers_the_canonical_query(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    # Sent as b=2&a=x%20y&a=1; signed as a=x%20y&a=1&b=2: sorted by key, repeats in order.
    headers = signed(agent, "GET", "/api/v1/me", "a=x%20y&a=1&b=2")
    response = make_client().get("/api/v1/me?b=2&a=x%20y&a=1", headers=headers)
    assert response.status_code == 200, response.text


def test_a_changed_body_breaks_the_signature(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    body = json.dumps({"x": 1}).encode()
    headers = signed(agent, "POST", "/api/v1/auth/logout", body=body)
    response = make_client().post(
        "/api/v1/auth/logout", content=b'{"x": 2}', headers=headers | _json()
    )
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "signature_invalid"


def test_a_signature_by_another_key_is_invalid(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine
) -> None:
    other = factory.agent(migrated, factory.project(migrated), agent.owner_id)
    headers = signed(other, "GET", "/api/v1/me")
    headers["Authorization"] = f"Maity-HMAC {agent.credential_id}"
    response = make_client().get("/api/v1/me", headers=headers)
    assert response.headers["Maity-Error"] == "signature_invalid"


def test_a_timestamp_outside_the_window_is_skew_with_the_server_time(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    old = int(clock.now().timestamp()) - 301
    response = make_client().get(
        "/api/v1/me", headers=signed(agent, "GET", "/api/v1/me", timestamp=old)
    )
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "timestamp_skew"
    assert "server_time" in response.json()["error"]["details"]


def test_a_nonce_is_used_once(make_client: ClientFactory, agent: factory.Agent) -> None:
    headers = signed(agent, "GET", "/api/v1/me")
    client = make_client()
    assert client.get("/api/v1/me", headers=headers).status_code == 200
    again = client.get("/api/v1/me", headers=headers)
    assert again.status_code == 401
    assert again.headers["Maity-Error"] == "nonce_reused"


def test_a_failed_signature_does_not_spend_the_nonce(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    nonce = secrets.token_urlsafe(16)
    bad = signed(agent, "GET", "/api/v1/me", nonce=nonce) | {"Maity-Signature": "0" * 64}
    client = make_client()
    assert client.get("/api/v1/me", headers=bad).headers["Maity-Error"] == "signature_invalid"
    good = signed(agent, "GET", "/api/v1/me", nonce=nonce)
    assert client.get("/api/v1/me", headers=good).status_code == 200


@pytest.mark.parametrize("nonce", ["a" * 21, "a" * 129, "0123456789abcdef", "a.b" * 8, "a b" * 8])
def test_a_nonce_outside_22_to_128_base64url_characters_is_invalid(
    make_client: ClientFactory, agent: factory.Agent, nonce: str
) -> None:
    headers = signed(agent, "GET", "/api/v1/me", nonce=nonce)
    response = make_client().get("/api/v1/me", headers=headers)
    assert response.headers["Maity-Error"] == "signature_invalid"


def test_a_non_ascii_nonce_is_not_base64url() -> None:
    from maity_hub.auth.caller import _nonce_shape

    assert not _nonce_shape("ü" * 22)
    assert _nonce_shape("A-z_0" * 5)


def test_header_shapes_refuse_non_ascii_and_oversized_values() -> None:
    from maity_hub.auth.caller import _hex64, _timestamp_shape

    assert not _timestamp_shape("١٢٣")  # Arabic-Indic digits pass str.isdigit()
    assert not _timestamp_shape("9" * 13)
    assert _timestamp_shape("1792000000")
    assert not _hex64("ä" * 64)
    assert _hex64("aB" * 32)


def test_a_nonce_of_22_and_of_128_characters_is_accepted(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client()
    for nonce in ("a" * 22, "b" * 128):
        headers = signed(agent, "GET", "/api/v1/me", nonce=nonce)
        assert client.get("/api/v1/me", headers=headers).status_code == 200


@pytest.mark.parametrize("missing", ["Maity-Timestamp", "Maity-Nonce", "Maity-Signature"])
def test_incomplete_signature_headers_are_invalid(
    make_client: ClientFactory, agent: factory.Agent, missing: str
) -> None:
    headers = signed(agent, "GET", "/api/v1/me")
    del headers[missing]
    response = make_client().get("/api/v1/me", headers=headers)
    assert response.headers["Maity-Error"] == "signature_invalid"


def test_the_canonical_string_of_the_contract() -> None:
    canonical = credentials.canonical_string("get", b"/api/v1/me", b"", "1792000000", "n" * 16, b"")
    assert canonical == "\n".join(
        [
            "MAITY-HMAC-V1",
            "GET",
            "/api/v1/me",
            "",
            "1792000000",
            "n" * 16,
            "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        ]
    )


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        (b"b=2&a=1", "a=1&b=2"),
        (b"a=2&a=1", "a=2&a=1"),
        (b"k=", "k="),
        (b"k", "k="),
        (b"q=a+b&p=%7e", "p=~&q=a%2Bb"),
        (b"x=%C3%BC", "x=%C3%BC"),
        ("x=ü".encode(), "x=%C3%BC"),  # raw UTF-8 is encoded once
        (b"x=%FF", "x=%FF"),  # not a valid UTF-8 byte, kept as it is
        (b"x=%FE", "x=%FE"),
    ],
)
def test_query_canonicalisation(raw: bytes, canonical: str) -> None:
    assert credentials.canonical_query(raw) == canonical


# --- forwarded headers -------------------------------------------------------------------


def test_forwarded_tls_from_a_trusted_proxy_counts(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client(
        base_url="http://hub.internal", peer="10.0.0.5", trusted_proxies=_cidr("10.0.0.0/8")
    )
    headers = bearer(agent) | {"X-Forwarded-Proto": "https", "X-Forwarded-For": "198.51.100.9"}
    assert client.get("/api/v1/me", headers=headers).status_code == 200


def test_forwarded_tls_from_anyone_else_changes_nothing(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client(base_url="http://hub.internal", peer="198.51.100.9")
    headers = bearer(agent) | {"X-Forwarded-Proto": "https"}
    response = client.get("/api/v1/me", headers=headers)
    assert response.headers["Maity-Error"] == "insecure_transport"


def test_a_forwarded_loopback_from_an_untrusted_peer_is_not_loopback(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    client = make_client(base_url="http://hub.internal", peer="198.51.100.9")
    headers = bearer(agent) | {"X-Forwarded-For": "127.0.0.1"}
    assert client.get("/api/v1/me", headers=headers).headers["Maity-Error"] == (
        "insecure_transport"
    )


# --- side effects ----------------------------------------------------------------------------


def test_a_call_renews_presence_and_the_leases_of_the_holder(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine
) -> None:
    project_id = _project_of(migrated, agent)
    start = clock.now()
    held = factory.card(
        migrated,
        project_id,
        agent.membership_id,
        status="in_progress",
        claim_holder=agent.membership_id,
        claim_since=start,
        lease_until=start + timedelta(minutes=5),
    )
    closed = factory.card(
        migrated,
        project_id,
        agent.membership_id,
        status="done",
        claim_holder=agent.membership_id,
        lease_until=start,
    )
    later = start + timedelta(hours=1)
    clock.set_source(lambda: later)
    assert make_client().get("/api/v1/me", headers=bearer(agent)).status_code == 200
    with migrated.connect() as conn:
        lease = dict(conn.execute(select(t.card.c.id, t.card.c.lease_until)).all())
        session = conn.execute(
            select(t.agent_session).where(t.agent_session.c.id == agent.session_id)
        ).one()
        credential = conn.execute(
            select(t.credential).where(t.credential.c.id == agent.credential_id)
        ).one()
        member_seen = conn.execute(
            select(t.membership.c.last_seen_at).where(t.membership.c.id == agent.membership_id)
        ).scalar()
        claim_session = conn.execute(
            select(t.card.c.claim_session_id).where(t.card.c.id == held)
        ).scalar()
    assert lease[held] == later + timedelta(seconds=7200)
    assert lease[closed] == start  # closed cards are left alone
    assert session.last_seen_at == later
    assert credential.last_used_at == later
    assert member_seen == later
    assert claim_session == agent.session_id  # the claim follows the live session


def test_the_long_poll_does_not_renew_leases(agent: factory.Agent, migrated: Engine) -> None:
    project_id = _project_of(migrated, agent)
    start = clock.now()
    card = factory.card(
        migrated,
        project_id,
        agent.membership_id,
        status="in_progress",
        claim_holder=agent.membership_id,
        lease_until=start,
    )
    facts = RequestFacts(
        method="GET",
        raw_path=b"/api/v1/projects/maity/events",
        raw_query=b"wait=55",
        headers={"authorization": f"Bearer {agent.value}"},
        cookies={},
        body=b"",
        origin=Origin("203.0.113.7", "https"),
        allow_plain_http=False,
    )
    clock.set_source(lambda: start + timedelta(hours=1))
    with migrated.begin() as conn:
        caller = authenticate(conn, facts, renew_leases=False)
    assert caller.session_id == agent.session_id
    with migrated.connect() as conn:
        lease = conn.execute(select(t.card.c.lease_until).where(t.card.c.id == card)).scalar()
        seen = conn.execute(
            select(t.agent_session.c.last_seen_at).where(t.agent_session.c.id == agent.session_id)
        ).scalar()
    assert lease == start
    assert seen == start + timedelta(hours=1)  # presence still counts


def test_a_credential_without_a_session_still_authenticates(
    make_client: ClientFactory, migrated: Engine
) -> None:
    project_id = factory.project(migrated)
    owner = factory.human(migrated)
    fresh = factory.agent(migrated, project_id, owner, with_session=False)
    assert make_client().get("/api/v1/me", headers=bearer(fresh)).status_code == 200


def _project_of(engine: Engine, agent: factory.Agent) -> str:
    with engine.connect() as conn:
        project_id: str = conn.execute(
            select(t.membership.c.project_id).where(t.membership.c.id == agent.membership_id)
        ).scalar_one()
    return project_id


def _cidr(value: str) -> Any:
    from maity_hub.config import parse_networks

    return parse_networks(value)


def _json() -> dict[str, str]:
    return {"Content-Type": "application/json"}


def test_distinct_raw_queries_never_share_a_canonical_form() -> None:
    assert credentials.canonical_query(b"q=a+b") != credentials.canonical_query(b"q=a%20b")
    assert credentials.canonical_query(b"x=%FF") != credentials.canonical_query(b"x=%FE")


# --- review round: malformed headers, proof before "revoked", restarts -------------


@pytest.mark.parametrize(
    "override",
    [
        {"Maity-Timestamp": "9" * 5000},
        {"Maity-Timestamp": "١٢٣"},  # digits, but not ASCII ones
        {"Maity-Signature": "g" * 64},
        {"Maity-Signature": "ab" * 31},
    ],
)
def test_malformed_signature_headers_are_signature_invalid_not_a_crash(
    make_client: ClientFactory, agent: factory.Agent, override: dict[str, str]
) -> None:
    headers = signed(agent, "GET", "/api/v1/me") | override
    try:
        response = make_client().get("/api/v1/me", headers=headers)
    except UnicodeEncodeError:
        pytest.skip("the HTTP client cannot send this header")
    assert response.status_code == 401
    assert response.headers["Maity-Error"] == "signature_invalid"


def test_a_request_signed_before_the_process_started_is_skew(
    make_client: ClientFactory, agent: factory.Agent, monkeypatch: pytest.MonkeyPatch
) -> None:
    from maity_hub.auth import caller

    monkeypatch.setattr(caller, "PROCESS_STARTED", int(clock.now().timestamp()) + 10)
    response = make_client().get("/api/v1/me", headers=signed(agent, "GET", "/api/v1/me"))
    assert response.headers["Maity-Error"] == "timestamp_skew"


def _revoke(engine: Engine, agent: factory.Agent) -> None:
    with engine.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(revoked_at=clock.now(), revoked_reason="by_owner")
        )


def test_revoked_is_only_told_to_whoever_proves_possession(
    make_client: ClientFactory, agent: factory.Agent, migrated: Engine
) -> None:
    _revoke(migrated, agent)
    client = make_client()
    guessed = f"mty1.{agent.credential_id}.{'C' * 43}"
    no_proof = client.get("/api/v1/me", headers={"Authorization": f"Bearer {guessed}"})
    assert no_proof.headers["Maity-Error"] == "unauthenticated"
    forged = signed(agent, "GET", "/api/v1/me") | {"Maity-Signature": "0" * 64}
    assert client.get("/api/v1/me", headers=forged).headers["Maity-Error"] == "signature_invalid"
    signed_ok = client.get("/api/v1/me", headers=signed(agent, "GET", "/api/v1/me"))
    assert signed_ok.headers["Maity-Error"] == "credential_revoked"
    assert client.get("/api/v1/me", headers=bearer(agent)).headers["Maity-Error"] == (
        "credential_revoked"
    )


def test_an_unknown_id_is_unauthenticated_on_both_paths(
    make_client: ClientFactory, agent: factory.Agent
) -> None:
    headers = signed(agent, "GET", "/api/v1/me")
    headers["Authorization"] = "Maity-HMAC crd-nobody"
    assert make_client().get("/api/v1/me", headers=headers).headers["Maity-Error"] == (
        "unauthenticated"
    )
