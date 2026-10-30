"""Opt-in counts-only public badges (§6.20)."""

from __future__ import annotations

import hashlib
from datetime import timedelta
from typing import Any
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, insert, select, update

from maity_hub import badges, clock, db, listening
from maity_hub import tables as t
from maity_hub.routes import auth, joins
from maity_hub.routes import badges as badge_routes
from tests import factory, flow
from tests.conftest import ClientFactory


@pytest.fixture
def setup(make_client: ClientFactory, migrated: Engine) -> tuple[flow.Human, TestClient, str]:
    owner = flow.human(make_client, migrated)
    flow.project(owner, name="Private project name")
    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    return owner, make_client(), project_id


def enable(owner: flow.Human, variant: str = "members") -> Any:
    response = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": variant}, "reason": "README"}
    )
    assert response.status_code == 200, response.text
    return response


def value(response: Any) -> str:
    node = ET.fromstring(response.content).find("{http://www.w3.org/2000/svg}text")
    assert node is not None
    return str(node.text)


@pytest.mark.parametrize("preset", ["hierarchical", "solo", "pool", "decentral", "hybrid"])
def test_every_preset_starts_private(
    setup: tuple[flow.Human, TestClient, str], preset: str
) -> None:
    owner, public, _ = setup
    created = flow.project(owner, f"p-{preset}", policy={"preset": preset})
    assert created["policy"]["badge"] == "off"
    response = public.get(f"/badge/maintainer/p-{preset}.svg")
    assert response.status_code == 404 and response.json()["error"]["code"] == "not_found"
    assert response.headers["cache-control"] == "no-store"


def test_policy_requires_a_human_admin(
    setup: tuple[flow.Human, TestClient, str], make_client: ClientFactory
) -> None:
    owner, public, _ = setup
    admin = flow.agent(make_client, owner, role="admin")
    refused = admin.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "members"}, "reason": "README"}
    )
    assert refused.status_code == 403
    unknown = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "names"}, "reason": "README"}
    )
    assert unknown.status_code == 400
    assert unknown.json()["error"]["details"]["fields"] == {"policy.badge": "unknown"}
    before = owner.get("/projects/maintainer/maity").json()["rules_version"]
    assert enable(owner).json()["rules_version"] == before + 1
    events = owner.get(
        "/projects/maintainer/maity/events", params={"after": 0, "limit": 100}
    ).json()["items"]
    event = [e for e in events if e["kind"] == "policy_changed"][-1]
    assert event["payload"]["old"]["badge"] == "off"
    assert event["payload"]["new"]["badge"] == "members"
    assert event["payload"]["reason"] == "README"
    changed = owner.patch(
        "/projects/maintainer/maity", {"policy": {"preset": "pool"}, "reason": "Preset"}
    )
    assert changed.json()["policy"]["badge"] == "members"


@pytest.mark.parametrize("state", ["off", "unknown", "archived"])
def test_hidden_badges_never_validate_a_cache(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine, state: str
) -> None:
    owner, public, project_id = setup
    enable(owner)
    etag = public.get("/badge/maintainer/maity.svg").headers["etag"]
    path = "/badge/maintainer/maity.svg"
    with migrated.begin() as conn:
        if state == "off":
            conn.execute(update(t.project).where(t.project.c.id == project_id).values(badge="off"))
        elif state == "unknown":
            path = "/badge/not-a-project.svg"
        else:
            conn.execute(update(t.project).where(t.project.c.id == project_id).values(state=state))
    response = public.get(path, headers={"If-None-Match": etag})
    assert response.status_code == 404
    assert response.json() == {
        "error": {"code": "not_found", "message": "no such resource", "details": {}}
    }
    assert response.headers["cache-control"] == "no-store" and "etag" not in response.headers


def test_active_counts_and_no_private_text(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    factory.agent(migrated, project_id, owner.id)
    removed = factory.agent(migrated, project_id, owner.id)
    other = factory.human(migrated, "private-human")
    factory.membership(migrated, project_id, human_id=other)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == removed.membership_id)
            .values(active=None)
        )
    enable(owner)
    response = public.get("/badge/maintainer/maity.svg")
    assert value(response) == "2 humans · 1 agent"
    for private in ("Private project name", "private-human", owner.id, removed.agent_id):
        assert private not in response.text
    assert "<script" not in response.text and "https://" not in response.text
    assert "<style" not in response.text
    assert response.headers["content-type"] == "image/svg+xml"
    assert response.headers["cache-control"] == "public, max-age=60"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "set-cookie" not in response.headers
    assert public.get("/api/v1/badge/maintainer/maity.svg").status_code == 404


def test_online_uses_canonical_presence(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    recent = factory.agent(migrated, project_id, owner.id)
    paused = factory.agent(migrated, project_id, owner.id)
    offline = factory.agent(migrated, project_id, owner.id, with_session=False)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == recent.membership_id)
            .values(last_seen_at=clock.now() - timedelta(hours=1))
        )
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == paused.membership_id)
            .values(paused_since=clock.now())
        )
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == offline.membership_id)
            .values(last_seen_at=clock.now())
        )
    enable(owner, "agents_online")
    response = public.get("/badge/maintainer/maity.svg")
    assert value(response) == "0 agents online" and 'fill="#5e6670"' in response.text
    assert "<style" not in response.text
    offline_etag = response.headers["etag"]
    listening.opened(recent.session_id or "")
    try:
        response = public.get("/badge/maintainer/maity.svg")
        assert value(response) == "1 agent online" and 'fill="#1a7f37"' in response.text
        assert "<style" in response.text and "<script" not in response.text
        assert response.headers["etag"] != offline_etag
        animated_etag = response.headers["etag"]
        cached = public.get("/badge/maintainer/maity.svg", headers={"If-None-Match": animated_etag})
        assert cached.status_code == 304 and cached.content == b""
    finally:
        listening.closed(recent.session_id or "")
    resting = public.get("/badge/maintainer/maity.svg", headers={"If-None-Match": animated_etag})
    assert resting.status_code == 200 and "<style" not in resting.text
    assert resting.headers["etag"] == offline_etag


def test_value_etag_and_revalidation(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    enable(owner)
    etag = public.get("/badge/maintainer/maity.svg").headers["etag"]
    assert public.get("/badge/maintainer/maity.svg").headers["etag"] == etag
    for candidate in (etag, f'"other", W/{etag}', "*"):
        cached = public.get("/badge/maintainer/maity.svg", headers={"If-None-Match": candidate})
        assert cached.status_code == 304 and cached.content == b""
        assert cached.headers["etag"] == etag
        assert cached.headers["cache-control"] == "public, max-age=60"
        assert cached.headers["x-content-type-options"] == "nosniff"
    factory.agent(migrated, project_id, owner.id)
    changed = public.get("/badge/maintainer/maity.svg", headers={"If-None-Match": etag})
    assert changed.status_code == 200 and changed.headers["etag"] != etag


def test_separate_source_rate_bucket(setup: tuple[flow.Human, TestClient, str]) -> None:
    owner, public, _ = setup
    enable(owner)
    for _ in range(60):
        assert public.get("/badge/maintainer/maity.svg").status_code == 200
    limited = public.get("/badge/maintainer/maity.svg")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert limited.headers["cache-control"] == "no-store"
    assert auth.LOGIN_BY_ADDRESS.blocked("203.0.113.7") == 0
    assert joins.EXCHANGE_BY_ADDRESS.blocked("203.0.113.7") == 0
    assert badge_routes.BY_ADDRESS.blocked("203.0.113.7") > 0


def test_join_host_redirects_instead_of_serving(
    setup: tuple[flow.Human, TestClient, str], make_client: ClientFactory
) -> None:
    owner, _, _ = setup
    enable(owner)
    client = make_client(base_url="https://join.example", join_url="https://join.example")
    response = client.get("/badge/maintainer/maity.svg", follow_redirects=False)
    assert response.status_code == 302 and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    ("text", "color", "reference_hash"),
    [
        (
            "1 human · 10 agents",
            "#1a66d9",
            "8526461130f3e551dc440796cc0fcf58990911b3be0ca449ac1fed9c57c6950d",
        ),
        (
            "7 agents online",
            "#1a7f37",
            "bcda77f67042a9530d20729bcced0bdbd142a005c87ed9725877e78e6c30b5eb",
        ),
    ],
)
def test_approved_examples(text: str, color: str, reference_hash: str) -> None:
    # Designer's example SVG hashes at brand-assets c30e02b.
    assert hashlib.sha256(badges.render(text, color)).hexdigest() == reference_hash


def test_approved_animated_example() -> None:
    # Independent designer example from the approved motion brand source.
    document = badges.render("7 agents online", "#1a7f37", animated=True)
    assert (
        hashlib.sha256(document).hexdigest()
        == "05b6ce46f8cb6c02cc1c888d8bdf7f634bec6da2a664bdf3a551782d8d25cfbe"
    )
    root = ET.fromstring(document)
    assert root.find("{http://www.w3.org/2000/svg}style") is not None
    assert root.find("{http://www.w3.org/2000/svg}script") is None


def test_xml_escaping() -> None:
    root = ET.fromstring(badges.render('A < B & "C"', "#1a66d9"))
    assert root.attrib["aria-label"] == 'maity: A < B & "C"'
    node = root.find("{http://www.w3.org/2000/svg}text")
    assert node is not None and node.text == 'A < B & "C"'


def test_migration_backfills_existing_projects(engine: Engine) -> None:
    db.migrate(engine, "0025")
    project_id = factory.project(engine)
    # The namespace migration (0060) needs a human owner for every project (§6.25).
    factory.membership(engine, project_id, human_id=factory.human(engine, "creator"))
    db.migrate(engine)
    with engine.connect() as conn:
        assert (
            conn.execute(select(t.project.c.badge).where(t.project.c.id == project_id)).scalar_one()
            == "off"
        )


def test_online_team_is_one_member(
    setup: tuple[flow.Human, TestClient, str], migrated: Engine
) -> None:
    owner, public, project_id = setup
    agent = factory.agent(migrated, project_id, owner.id)
    with migrated.begin() as conn:
        conn.execute(
            update(t.membership)
            .where(t.membership.c.id == agent.membership_id)
            .values(last_seen_at=clock.now())
        )
        # A call marks the instance too (§5.3: each instance has its own presence).
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == agent.credential_id)
            .values(last_used_at=clock.now())
        )
        conn.execute(
            insert(t.credential).values(
                id="crd-badge-sibling",
                membership_id=agent.membership_id,
                instance="abcd",
                verifier="0" * 64,
                created_at=clock.now(),
                last_used_at=clock.now(),
            )
        )
        conn.execute(
            insert(t.agent_session).values(
                id="ses-badge-sibling",
                credential_id="crd-badge-sibling",
                membership_id=agent.membership_id,
                harness="test",
                model="test",
                client="test",
                started_at=clock.now(),
                last_seen_at=clock.now(),
                acknowledged_seq=0,
                live=True,
            )
        )
    enable(owner, "agents_online")
    assert value(public.get("/badge/maintainer/maity.svg")) == "1 agent online"


@pytest.mark.parametrize(
    ("allow", "status", "expected"),
    [
        (False, 200, b"no-store"),
        (True, 200, b"public, max-age=60"),
        (True, 304, b"public, max-age=60"),
        (True, 404, b"no-store"),
    ],
)
def test_public_cache_exception_is_narrow(allow: bool, status: int, expected: bytes) -> None:
    import asyncio

    from maity_hub.middleware import _with_headers

    sent: list[Any] = []

    async def send(message: Any) -> None:
        sent.append(message)

    async def check() -> None:
        await _with_headers(send, public=b"public, max-age=60" if allow else None)(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"cache-control", b"public, max-age=60")],
            }
        )

    asyncio.run(check())
    assert dict(sent[0]["headers"])[b"cache-control"] == expected


def test_the_badge_alone_needs_no_reason(setup: tuple[flow.Human, TestClient, str]) -> None:
    """§6.20: a policy change of `badge` alone takes `reason` optionally."""
    owner, public, _ = setup
    before = owner.get("/projects/maintainer/maity").json()["rules_version"]
    changed = owner.patch("/projects/maintainer/maity", {"policy": {"badge": "members"}})
    assert changed.status_code == 200, changed.text
    assert changed.json()["policy"]["badge"] == "members"
    assert changed.json()["rules_version"] == before + 1  # still a policy change
    assert public.get("/badge/maintainer/maity.svg").status_code == 200
    events = owner.get(
        "/projects/maintainer/maity/events", params={"after": 0, "limit": 100}
    ).json()["items"]
    event = [e for e in events if e["kind"] == "policy_changed"][-1]
    assert (event["payload"]["new"]["badge"], event["payload"]["reason"]) == ("members", None)


def test_the_badge_with_another_policy_field_still_needs_a_reason(
    setup: tuple[flow.Human, TestClient, str],
) -> None:
    owner, public, _ = setup
    mixed = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "members", "subtasks": "direct"}}
    )
    assert mixed.status_code == 400, mixed.text
    assert mixed.json()["error"]["details"]["fields"] == {"reason": "required"}
    assert public.get("/badge/maintainer/maity.svg").status_code == 404  # nothing was written
    other = owner.patch("/projects/maintainer/maity", {"policy": {"subtasks": "direct"}})
    assert other.status_code == 400
    state = owner.patch(
        "/projects/maintainer/maity", {"policy": {"badge": "members"}, "state": "review"}
    )
    assert state.status_code == 400  # a state change keeps its reason rule
