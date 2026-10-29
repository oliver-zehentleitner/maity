"""docs/api.md §3: the join link, the join page and the exchange."""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from sqlalchemy import Engine, select

from maity_hub import clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory

CODE = re.compile(r"^[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}$")


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


def _token(created: dict[str, str]) -> str:
    return created["join_url"].rsplit("/", 1)[1]


# --- §3.1 the join link ---------------------------------------------------------------


def test_a_join_answers_the_paste_line_once(owner: flow.Human) -> None:
    response = owner.post(
        "/projects/maintainer/maity/joins",
        {
            "agent": {"handle": "agent-b", "display_name": "Agent B"},
            "trust": "member",
            "role": "coder",
            "areas": ["hub/"],
            "capabilities": [],
            "ttl_seconds": 900,
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert set(body) == {
        "id",
        "join_url",
        "code",
        "paste_line",
        "agent_id",
        "project",
        "expires_at",
        "via",
    }
    assert body["via"] == "public"  # no join host configured
    assert body["join_url"].startswith("https://hub.example/join/")
    assert len(_token(body)) >= 22  # 128 bits, base64url
    assert CODE.match(body["code"])
    assert body["paste_line"] == f"maity join {body['join_url']} --code {body['code']}"
    assert body["agent_id"].startswith("agt-")
    assert body["project"] == "maintainer/maity"
    listed = owner.get("/projects/maintainer/maity/joins").json()["items"]
    assert set(listed[0]) == {
        "id",
        "agent_id",
        "trust",
        "role",
        "created_by",
        "created_at",
        "expires_at",
        "used_at",
        "burned",
        "revoked_at",
        "via",
        "new_instance",
        "replaces",
        "instance",
    }
    assert body["code"] not in str(listed) and _token(body) not in str(listed)


def test_the_profile_is_created_with_the_join(owner: flow.Human) -> None:
    created = flow.join(owner, "maity", agent={"handle": "agent-b", "display_name": "Agent B"})
    agents = owner.get("/agents").json()["items"]
    assert [a["id"] for a in agents] == [created["agent_id"]]
    assert agents[0]["memberships"] == []  # the exchange makes the membership


def test_a_join_names_an_own_agent_or_a_new_one(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    mine = owner.post("/agents", {"handle": "mine", "display_name": "Mine"}).json()
    assert flow.join(owner, "maity", agent={"id": mine["id"]})["agent_id"] == mine["id"]
    other = flow.human(make_client, migrated, "someone")
    theirs = other.post("/agents", {"handle": "theirs", "display_name": "Theirs"}).json()
    response = owner.post("/projects/maintainer/maity/joins", {"agent": {"id": theirs["id"]}})
    assert response.json()["error"]["details"]["fields"] == {"agent.id": "not_yours"}
    neither = owner.post("/projects/maintainer/maity/joins", {"agent": {}})
    assert neither.json()["error"]["details"]["fields"] == {"agent": "id_or_handle"}


@pytest.mark.parametrize("ttl", [59, 3601])
def test_the_ttl_is_bounded(owner: flow.Human, ttl: int) -> None:
    response = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"handle": "aa", "display_name": "A"}, "ttl_seconds": ttl},
    )
    assert response.json()["error"]["details"]["fields"] == {"ttl_seconds": "out_of_range"}


def test_joins_need_members_admin(owner: flow.Human, make_client: ClientFactory) -> None:
    admin_agent = flow.agent(make_client, owner, role="admin")
    response = admin_agent.post(
        "/projects/maintainer/maity/joins", {"agent": {"handle": "x", "display_name": "X"}}
    )
    assert response.status_code == 403
    assert response.headers["Maity-Error"] == "forbidden"


def test_a_join_for_an_existing_member_keeps_the_membership(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    first = flow.agent(make_client, owner, role="member", areas=["hub/"])
    differing = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"id": first.id}, "trust": "admin", "areas": ["web/"], "capabilities": []},
    )
    assert differing.status_code == 400
    assert differing.json()["error"]["details"]["fields"] == {
        "trust": "differs_from_membership",
        "areas": "differs_from_membership",
    }
    owner.patch(f"/projects/maintainer/maity/members/{first.id}", {"team": {"max_instances": 2}})
    second_clone = flow.agent(
        make_client, owner, agent={"id": first.id}, areas=["hub/"], new_instance=True
    )
    assert second_clone.id == first.id
    assert second_clone.credential_id != first.credential_id
    with migrated.connect() as conn:
        memberships = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == first.id)
        ).all()
    assert len(memberships) == 1 and (memberships[0].trust, memberships[0].role) == (
        "member",
        "coder",
    )


def test_delete_revokes_an_unused_join_and_refuses_a_spent_one(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    unused = flow.join(owner, "maity")
    revoked = owner.delete(f"/projects/maintainer/maity/joins/{unused['id']}")
    assert revoked.status_code == 200 and revoked.json()["revoked_at"]
    again = owner.delete(f"/projects/maintainer/maity/joins/{unused['id']}")
    assert again.status_code == 200 and again.json() == revoked.json()
    assert flow.exchange(make_client(), unused).headers["Maity-Error"] == "not_found"

    used = flow.join(owner, "maity")
    flow.exchange(make_client(), used)
    response = owner.delete(f"/projects/maintainer/maity/joins/{used['id']}")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "invalid_transition"
    assert response.json()["error"]["details"] == {"from": "used", "to": "revoked"}


# --- §3.2 the join page ---------------------------------------------------------------


def test_the_page_is_markdown_for_an_agent(owner: flow.Human, make_client: ClientFactory) -> None:
    created = flow.join(
        owner,
        "maity",
        agent={"handle": "agent-b", "display_name": "B"},
        role="member",
        areas=["hub/"],
    )
    client = make_client()
    for path in (f"/join/{_token(created)}", f"/api/v1/join/{_token(created)}"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/markdown; charset=utf-8"
        text = response.text
        assert text.startswith("# Join Maity on Maity")
        for heading in range(1, 8):
            assert f"\n## {heading}. " in text
        assert "`agent-b`" in text and "`hub/`" in text
        assert "| Your handle | `agent-b` |" in text  # the row `maity join` reads (cli)
        assert "~/.local/state/maity/hub.example/agent-b" in text
        assert f"https://hub.example/api/v1/join/{_token(created)}" in text
        assert created["code"] not in text
        assert "{{" not in text and "Template for the join page" not in text


@pytest.mark.parametrize("repository", [None, "https://github.com/acme/widget"])
def test_join_page_names_the_expected_repository(
    owner: flow.Human, make_client: ClientFactory, repository: str | None
) -> None:
    if repository:
        assert (
            owner.patch(
                "/projects/maintainer/maity", {"repository": {"url": repository}}
            ).status_code
            == 200
        )
    created = flow.join(owner, "maity")
    for accept in ["text/markdown", "text/html"]:
        response = make_client().get(f"/join/{_token(created)}", headers={"Accept": accept})
        assert response.status_code == 200
        assert "Expected repository" in response.text
        assert (repository or "not configured") in response.text.replace("\\", "")
        assert "{{project_repository}}" not in response.text
        assert created["code"] not in response.text


def test_the_page_is_html_for_a_browser_with_no_form(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    created = flow.join(owner, "maity")
    response = make_client().get(f"/join/{_token(created)}", headers={"Accept": "text/html"})
    assert response.headers["content-type"] == "text/html; charset=utf-8"
    assert response.headers["Content-Security-Policy"] == "default-src 'self'"
    page = response.text.lower()
    assert "<form" not in page and "<script" not in page and "<input" not in page
    assert '<a href="/">' in page
    assert created["code"] not in response.text


def test_a_project_name_cannot_inject_html_or_markdown(
    make_client: ClientFactory, migrated: Engine
) -> None:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "evil", name="<script>x</script> [click](javascript:alert(1))")
    created = flow.join(owner, "evil")
    page = make_client().get(f"/join/{_token(created)}", headers={"Accept": "text/html"}).text
    assert "<script>x" not in page and 'href="javascript' not in page


def test_a_spent_or_unknown_token_has_no_page(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    used = flow.join(owner, "maity")
    flow.exchange(make_client(), used)
    expired = flow.join(owner, "maity", ttl_seconds=60)
    start = clock.now()
    clock.set_source(lambda: start + timedelta(seconds=61))
    client = make_client()
    for path in (
        f"/join/{_token(used)}",
        f"/join/{_token(expired)}",
        "/join/nope",
        "/api/v1/join/nope",
    ):
        response = client.get(path)
        assert response.status_code == 404, path
        assert response.headers["Maity-Error"] == "not_found"


# --- §3.3 the exchange -------------------------------------------------------------------


def test_the_exchange_answers_the_bare_credential_and_facts_in_headers(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    created = flow.join(owner, "maity")
    response = flow.exchange(make_client(), created)
    assert response.status_code == 201
    assert response.headers["content-type"] == "text/plain; charset=utf-8"
    assert response.headers["Cache-Control"] == "no-store"
    assert re.fullmatch(r"mty1\.crd-[0-9a-z]+\.[A-Za-z0-9_-]{43}", response.text)
    assert response.headers["Maity-Credential-Id"] == response.text.split(".")[1]
    assert response.headers["Maity-Member-Id"] == created["agent_id"]
    assert response.headers["Maity-Project"] == "maintainer/maity"
    assert response.headers["Maity-Hub"] == "https://hub.example"
    me = make_client().get("/api/v1/me", headers={"Authorization": f"Bearer {response.text}"})
    assert me.json()["member"]["id"] == created["agent_id"]


def test_the_exchange_is_single_use(owner: flow.Human, make_client: ClientFactory) -> None:
    created = flow.join(owner, "maity")
    assert flow.exchange(make_client(), created).status_code == 201
    assert flow.exchange(make_client(), created).headers["Maity-Error"] == "not_found"


def test_the_code_is_read_the_crockford_way(owner: flow.Human, make_client: ClientFactory) -> None:
    created = flow.join(owner, "maity")
    sloppy = created["code"].lower().replace("-", " ").replace("1", "l").replace("0", "o")
    response = flow.exchange(make_client(), {**created, "code": sloppy})
    assert response.status_code == 201


def test_three_wrong_codes_burn_the_join(owner: flow.Human, make_client: ClientFactory) -> None:
    created = flow.join(owner, "maity")
    client = make_client()
    for _ in range(3):
        wrong = flow.exchange(client, {**created, "code": "ZZZZ-ZZZZ-ZZZZ"})
        assert wrong.status_code == 403
        assert wrong.headers["Maity-Error"] == "code_invalid"
    assert flow.exchange(client, created).headers["Maity-Error"] == "not_found"
    listed = owner.get("/projects/maintainer/maity/joins").json()["items"][0]
    assert listed["burned"] is True and listed["used_at"] is None


def test_two_wrong_codes_do_not_burn(owner: flow.Human, make_client: ClientFactory) -> None:
    created = flow.join(owner, "maity")
    client = make_client()
    for _ in range(2):
        flow.exchange(client, {**created, "code": "ZZZZ-ZZZZ-ZZZZ"})
    assert flow.exchange(client, created).status_code == 201


def test_the_exchange_is_limited_to_ten_per_minute(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    client = make_client()
    for _ in range(10):
        client.post("/api/v1/join/nope", json={"code": "x", "client": "curl"})
    response = client.post("/api/v1/join/nope", json={"code": "x", "client": "curl"})
    assert response.status_code == 429
    assert response.headers["Maity-Error"] == "rate_limited"


def test_the_exchange_over_plain_http_off_loopback_is_refused(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    created = flow.join(owner, "maity")
    plain = make_client(base_url="http://hub.example")
    assert flow.exchange(plain, created).headers["Maity-Error"] == "insecure_transport"
    loopback = make_client(base_url="http://localhost:8080", peer="127.0.0.1")
    assert flow.exchange(loopback, created).status_code == 201


def test_the_exchange_emits_member_joined_to_everyone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    created = flow.join(owner, "maity", agent={"handle": "agent-b", "display_name": "B"})
    flow.exchange(make_client(), created)
    with migrated.connect() as conn:
        rows = conn.execute(
            select(t.event).where(t.event.c.kind == "member_joined").order_by(t.event.c.seq)
        ).all()
    joined = rows[-1]
    assert joined.audience == ["all"]
    assert joined.payload["id"] == created["agent_id"] and joined.payload["handle"] == "agent-b"


def test_the_exchange_records_the_client_and_needs_it(
    owner: flow.Human, make_client: ClientFactory
) -> None:
    created = flow.join(owner, "maity")
    token = _token(created)
    missing = make_client().post(f"/api/v1/join/{token}", json={"code": created["code"]})
    assert missing.json()["error"]["details"]["fields"] == {"client": "missing"}
    agent = flow.agent(make_client, owner)
    listed = owner.get(f"/projects/maintainer/maity/members/{agent.id}/credentials").json()["items"]
    assert listed[0]["client"] == "curl"
    assert listed[0]["resumed_at"] is None  # "never resumed"


def test_concurrent_wrong_codes_burn_after_exactly_three(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    created = flow.join(owner, "maity")
    clients = [make_client(peer=f"203.0.113.{i + 20}") for i in range(8)]

    def guess(client: object) -> str:
        response = flow.exchange(client, {**created, "code": "ZZZZ-ZZZZ-ZZZZ"})  # type: ignore[arg-type]
        return str(response.headers["Maity-Error"])

    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(guess, clients))
    assert outcomes.count("code_invalid") == 3  # exactly three codes were compared
    assert set(outcomes) <= {"code_invalid", "not_found"}
    with migrated.connect() as conn:
        row = conn.execute(select(t.join_link).where(t.join_link.c.id == created["id"])).one()
    assert (row.failed_attempts, row.burned_at is not None) == (3, True)
    assert flow.exchange(make_client(), created).headers["Maity-Error"] == "not_found"


@pytest.mark.parametrize(
    "area", ["hub/`x", "a\n\n## Injected", "[x](https://evil.example)", "../etc", "a/../b", ""]
)
def test_areas_are_plain_paths(owner: flow.Human, area: str) -> None:
    response = owner.post(
        "/projects/maintainer/maity/joins",
        {"agent": {"handle": "aa", "display_name": "A"}, "areas": [area]},
    )
    assert response.json()["error"]["details"]["fields"] == {"areas": "invalid_path"}


def test_ordinary_areas_are_fine(owner: flow.Human) -> None:
    flow.join(owner, "maity", areas=["/", "hub/", "context/", "docs/api.md", "web/js/app.js"])


def test_a_new_instance_of_an_admin_agent_is_the_owners_to_give(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    """A join that leaves trust and role out takes the member's own: for an agent the
    owner raised to trust `admin`, that is a credential with trust admin, which only an
    owner hands out, even to the agent's own human (§2.3 "The owner's rights")."""
    from tests import factory

    with migrated.connect() as conn:
        project_id = conn.execute(select(t.project.c.id)).scalar_one()
    deputy = flow.human(make_client, migrated, "deputy")
    factory.membership(migrated, project_id, "admin", human_id=deputy.id)
    agent = flow.agent(make_client, deputy, "maintainer/maity")
    members = "/projects/maintainer/maity/members"
    assert owner.patch(f"{members}/{agent.id}", {"trust": "admin"}).status_code == 200
    deputy.patch(f"{members}/{agent.id}", {"team": {"max_instances": 3}})
    refused = deputy.post(
        "/projects/maintainer/maity/joins", {"agent": {"id": agent.id}, "new_instance": True}
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["error"]["details"] == {"reason": "owner_only"}
