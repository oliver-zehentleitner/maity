"""docs/api.md §17: the change ticker — the manual post, dedupe, the audience and the
subscriptions, the hub's own decision and release items, the listing, the shaping per
reader, waking, the resume packet."""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import Engine, select

from maity_hub import events, ticker, ticker_read
from maity_hub import tables as t
from maity_hub.routes import ticker as ticker_routes
from tests import flow
from tests.conftest import ClientFactory
from tests.test_requests import answer, asked
from tests.test_tasks import task


@pytest.fixture(autouse=True)
def _limits() -> None:
    ticker_routes.POSTS.reset()
    ticker_routes.POSTS_TO_ALL.reset()


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    owner = flow.human(make_client, migrated)
    flow.project(owner, "maity")
    return owner


@pytest.fixture
def team(make_client: ClientFactory, owner: flow.Human) -> dict[str, flow.Agent]:
    """An admin agent owning context/, members owning hub/ and hub/maity_hub/ (narrower)."""
    return {
        "admin": flow.agent(make_client, owner, role="admin", areas=["context/"]),
        "hub": flow.agent(make_client, owner, areas=["hub/"]),
        "claims": flow.agent(make_client, owner, areas=["hub/maity_hub/"]),
        "web": flow.agent(make_client, owner, areas=["web/"]),
    }


def post(who: Any, **body: Any) -> Any:
    return who.post("/projects/maity/ticker", body)


def note(who: Any, text: str = "Staging is down for an hour.", **body: Any) -> dict[str, Any]:
    response = post(who, type="note", text=text, **{"areas": ["hub/"], **body})
    assert response.status_code == 201, response.text
    result: dict[str, Any] = response.json()
    return result


def listed(who: Any, query: str = "") -> list[dict[str, Any]]:
    response = who.get(f"/projects/maity/ticker{query}")
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def enable(owner: flow.Human, **extra: Any) -> None:
    response = owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": True, **extra}}})
    assert response.status_code == 200, response.text


def reasons(event: dict[str, Any]) -> dict[str, list[str]]:
    return {r["member_id"]: r["why"] for r in event["payload"]["reasons"]}


# --- §17.6 the manual post -------------------------------------------------------------


def test_a_note_goes_to_the_owners_of_its_areas_and_is_an_event(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(team["admin"], areas=["hub/maity_hub/claims.py", "web/"])
    assert item["kind"] == "ticker"
    p = item["payload"]
    assert (p["type"], p["text"], p["url"], p["dedupe_key"], p["origin"]) == (
        "note",
        "Staging is down for an hour.",
        None,
        None,
        {"via": "manual", "delivery": None},
    )
    assert p["areas"] == ["hub/maity_hub/claims.py", "web/"]
    assert item["actor"]["member_id"] == team["admin"].id
    # Shaped for the poster, an agent: its own entry only, `all` and its own token.
    assert item["audience"] == ["all"]
    as_owner = listed(owner, "?for=all")[0]
    assert as_owner["seq"] == item["seq"]
    with_reasons = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    # The narrowest area wins: hub/maity_hub/ before hub/ (§6.2).
    assert reasons(with_reasons) == {
        team["claims"].id: ["area_owner:hub/maity_hub/"],
        team["web"].id: ["area_owner:web/"],
    }
    assert with_reasons["audience"] == [
        "all",
        f"member:{team['claims'].id}",
        f"member:{team['web'].id}",
    ]


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        ({"type": "merge", "text": "x"}, {"type": "not_for_type"}),
        ({"type": "decision", "text": "x"}, {"type": "not_for_type"}),
        ({"type": "nonsense", "text": "x", "to": "all"}, {"type": "invalid"}),
        ({"text": "x"}, {"type": "required"}),
        ({"type": "note", "areas": ["/"]}, {"text": "required"}),
        ({"type": "note", "text": "x" * 281, "areas": ["/"]}, {"text": "invalid"}),
        ({"type": "note", "text": "x"}, {"areas": "required"}),
        (
            {"type": "note", "text": "x", "areas": ["/"], "url": "http://example.org"},
            {"url": "invalid"},
        ),
        ({"type": "note", "text": "x", "to": ["somebody"]}, {"to": "invalid"}),
        ({"type": "note", "text": "x", "to": ["all"]}, {"to": "invalid"}),
        ({"type": "deploy", "text": "x"}, {"deploy": "required"}),
        ({"type": "deploy", "text": "x", "deploy": {"environment": "e"}}, {"deploy": "required"}),
        (
            {"type": "deploy", "text": "x", "deploy": {"environment": "e" * 65, "sha": "abc1234"}},
            {"deploy.environment": "invalid"},
        ),
        (
            {
                "type": "deploy",
                "text": "x",
                "deploy": {"environment": "e", "sha": "a", "log_url": "ftp://x"},
            },
            {"deploy.log_url": "invalid"},
        ),
        (
            {"type": "note", "text": "x", "to": "all", "deploy": {"environment": "e", "sha": "a"}},
            {"deploy": "not_for_type"},
        ),
        ({"type": "release", "text": "x"}, {"release_task_id": "required"}),
    ],
)
def test_a_post_is_checked_field_by_field(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    response = post(owner, **body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["details"]["fields"] == fields


def test_a_release_names_a_done_release_card(owner: flow.Human) -> None:
    card = task(owner)
    response = post(owner, type="release", text="Released", release_task_id=card["id"])
    assert response.json()["error"]["details"]["fields"] == {"release_task_id": "not_done"}


def test_a_member_named_in_to_must_be_one(owner: flow.Human) -> None:
    response = post(owner, type="note", text="x", to=["member:agt-nobody"])
    assert response.json()["error"]["details"]["fields"] == {"to": "invalid"}


def test_only_owners_and_admins_post(owner: flow.Human, team: dict[str, flow.Agent]) -> None:
    assert post(team["hub"], type="note", text="x", to="all").status_code == 403
    assert post(team["admin"], type="note", text="x", to="all").status_code == 201


def test_to_all_reaches_everyone_and_never_wakes_the_poster(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(owner, to="all", areas=None)
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    by = {r["member_id"]: r for r in full["payload"]["reasons"]}
    assert set(by) == {owner.id, *(a.id for a in team.values())}
    assert all(r["why"] == ["posted_to_all"] for r in by.values())
    assert by[owner.id]["wake"] is False
    assert all(by[a.id]["wake"] for a in team.values())


def test_a_token_list_is_resolved_to_members(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(owner, to=["role:admin", "area:web/x.js", f"member:{team['hub'].id}"], areas=None)
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert reasons(full) == {
        team["admin"].id: ["addressed"],
        team["web"].id: ["addressed"],
        team["hub"].id: ["addressed"],
    }
    assert not any(a.startswith(("role:", "area:")) for a in full["audience"])


def test_a_deploy_is_posted_once_per_environment_and_sha(owner: flow.Human) -> None:
    body = {
        "type": "deploy",
        "text": "Deployed",
        "deploy": {"environment": "staging", "sha": "1cddc4d"},
    }
    first = post(owner, **body)
    assert first.status_code == 201, first.text
    assert first.json()["payload"]["dedupe_key"] == "deploy:staging:1cddc4d"
    again = post(owner, **body)
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "ticker_duplicate"
    assert again.json()["error"]["details"] == {"seq": first.json()["seq"]}


def test_five_posts_to_everyone_an_hour(owner: flow.Human) -> None:
    for n in range(5):
        assert post(owner, type="note", text=f"n{n}", to="all").status_code == 201
    over = post(owner, type="note", text="one more", to="all")
    assert over.status_code == 429 and over.json()["error"]["code"] == "rate_limited"
    assert post(owner, type="note", text="to whom it concerns", areas=["/"]).status_code == 201


def test_a_refused_post_spends_no_limit(owner: flow.Human) -> None:
    for _ in range(25):
        assert post(owner, type="merge", text="x").status_code == 400
    assert post(owner, type="note", text="still fine", to="all").status_code == 201


# --- §17.8 subscriptions ---------------------------------------------------------------


def test_one_subscription_is_changed_by_what_it_adds_and_removes(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    agent = team["web"]
    assert agent.get("/projects/maity/ticker/subscription").json() == {
        "follow": {"areas": [], "types": []},
        "mute": {"areas": [], "types": []},
        "updated_at": None,
    }
    changed = agent.patch(
        "/projects/maity/ticker/subscription",
        {"add": {"follow": {"areas": ["cli/"], "types": ["release"]}, "mute": {"types": ["note"]}}},
    ).json()
    assert changed["follow"] == {"areas": ["cli/"], "types": ["release"]}
    assert changed["mute"] == {"areas": [], "types": ["note"]}
    again = agent.patch(
        "/projects/maity/ticker/subscription",
        {"add": {"follow": {"areas": ["cli/"]}}, "remove": {"mute": {"types": ["note"]}}},
    ).json()
    assert again["follow"]["areas"] == ["cli/"] and again["mute"]["types"] == []


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        (
            {"add": {"follow": {"areas": ["a/"]}}, "remove": {"follow": {"areas": ["a/"]}}},
            {"follow.areas": "invalid"},
        ),
        ({"add": {"mute": {"types": ["merges"]}}}, {"mute.types": "invalid"}),
        (
            {"add": {"follow": {"areas": [f"a{n}/" for n in range(21)]}}},
            {"follow.areas": "too_many"},
        ),
    ],
)
def test_a_subscription_change_is_checked(
    owner: flow.Human, body: dict[str, Any], fields: dict[str, str]
) -> None:
    response = owner.patch("/projects/maity/ticker/subscription", body)
    assert response.status_code == 400
    assert response.json()["error"]["details"]["fields"] == fields


def test_the_change_is_read_by_the_member_and_the_human_owners_only(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    agent = team["web"]
    agent.patch("/projects/maity/ticker/subscription", {"add": {"mute": {"areas": ["context/"]}}})
    with migrated.connect() as conn:
        seq = conn.execute(
            select(t.event.c.seq).where(t.event.c.kind == "ticker_subscription_changed")
        ).scalar_one()

    def sees(who: Any) -> bool:
        items = who.get(f"/projects/maity/events?after={seq - 1}").json()["items"]
        return any(i["seq"] == seq for i in items)

    assert sees(agent) and sees(owner)
    assert not sees(team["admin"]), "not even an admin agent"
    assert not sees(team["hub"])


def test_follows_add_and_mutes_remove_or_mark(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    team["web"].patch(
        "/projects/maity/ticker/subscription", {"add": {"follow": {"areas": ["hub/"]}}}
    )
    team["hub"].patch("/projects/maity/ticker/subscription", {"add": {"mute": {"types": ["note"]}}})
    team["claims"].patch(
        "/projects/maity/ticker/subscription",
        {"add": {"follow": {"types": ["note"]}, "mute": {"areas": ["hub/"]}}},
    )
    item = note(owner, areas=["hub/a.py", "hub/maity_hub/b.py"])
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    by = {r["member_id"]: r for r in full["payload"]["reasons"]}
    assert by[team["web"].id]["why"] == ["follow:hub/"] and by[team["web"].id]["wake"]
    assert team["hub"].id not in by, "a mute without a follow removes the member"
    claims = by[team["claims"].id]
    assert (claims["muted"], claims["wake"]) == (
        True,
        False,
    ), "followed and muted: listed, not woken"
    assert f"member:{team['claims'].id}" not in full["audience"]
    assert listed(team["claims"], "?for=me")[0]["muted"] is True


# --- §17.9 the listing -------------------------------------------------------------------


def test_the_listing_is_the_compact_form_with_the_readers_own_reasons(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(owner, areas=["web/"], url="https://example.org/x")
    [mine] = listed(team["web"], "?for=me")
    assert mine == {
        "id": f"tck-{item['seq']}",
        "seq": item["seq"],
        "at": item["at"],
        "type": "note",
        "text": "Staging is down for an hour.",
        "url": "https://example.org/x",
        "actor": item["actor"],
        "subject": None,
        "areas": ["web/"],
        "contract": None,
        "tasks": [],
        "for_me": True,
        "why": ["area_owner:web/"],
        "muted": False,
        "detail": None,
        "redacted": False,
    }
    assert listed(team["hub"], "?for=me") == []
    [theirs] = listed(team["hub"])
    assert (theirs["for_me"], theirs["why"]) == (False, [])


def test_the_listing_filters_and_pages(owner: flow.Human) -> None:
    seqs = [
        note(owner, text=f"n{n}", areas=["hub/"] if n % 2 else ["web/"])["seq"] for n in range(5)
    ]
    post(owner, type="deploy", text="Deployed", deploy={"environment": "prod", "version": "1.0.0"})
    assert [i["type"] for i in listed(owner, "?type=deploy")] == ["deploy"]
    assert [i["seq"] for i in listed(owner, "?type=note&area=hub/")] == [seqs[3], seqs[1]]
    first = owner.get("/projects/maity/ticker?type=note&limit=2").json()
    assert [i["seq"] for i in first["items"]] == [seqs[4], seqs[3]]
    second = owner.get(
        f"/projects/maity/ticker?type=note&limit=2&cursor={first['next_cursor']}"
    ).json()
    assert [i["seq"] for i in second["items"]] == [seqs[2], seqs[1]]
    other = owner.get(f"/projects/maity/ticker?type=deploy&limit=2&cursor={first['next_cursor']}")
    assert other.status_code == 400, "a cursor is valid for one filter set"
    after = listed(owner, f"?type=note&after={seqs[2]}")
    assert [i["seq"] for i in after] == [seqs[3], seqs[4]], "after= is oldest first"


@pytest.mark.parametrize(
    "query",
    [
        "?type=merges",
        "?for=you",
        "?limit=0",
        "?limit=201",
        "?since=2026-10-22T10:00:00",
        "?after=x",
    ],
)
def test_the_listing_query_is_checked(owner: flow.Human, query: str) -> None:
    assert owner.get(f"/projects/maity/ticker{query}").status_code == 400


# --- §17.2, §17.3, §17.5 the hub's decisions ---------------------------------------------


def test_a_decision_goes_to_who_may_read_its_request_and_nobody_else(
    owner: flow.Human, team: dict[str, flow.Agent], make_client: ClientFactory
) -> None:
    enable(owner)
    asker = team["hub"]
    request = asked(
        asker,
        to="owner",
        options=[{"id": "a", "label": "Argon2id"}, {"id": "b", "label": "SHA-256"}],
    )
    assert answer(owner, request, reply_id="a").status_code == 200
    [item] = listed(asker)
    assert item["type"] == "decision" and item["for_me"] and item["why"] == ["decision_asker"]
    assert item["text"] == f"Decided: {request['id']}"
    assert item["detail"] == {"request_title": "Which?", "reply_label": "Argon2id"}
    assert listed(team["web"]) == [], "a member who may not read the request gets no item"
    assert listed(team["admin"]) != [], "an admin agent holds requests:answer"
    events_of_web = team["web"].get("/projects/maity/events?after=0").json()["items"]
    assert not any(e["kind"] == "ticker" for e in events_of_web)
    raw = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert "all" not in raw["audience"]
    assert not any(a.startswith("role:") for a in raw["audience"])


def test_no_item_while_the_ticker_is_off(owner: flow.Human, team: dict[str, flow.Agent]) -> None:
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Go with the first one.")
    assert listed(owner) == []


def test_talk_and_info_are_no_decisions(owner: flow.Human, team: dict[str, flow.Agent]) -> None:
    enable(owner)
    info = asked(team["hub"], to="owner", **{"class": "info"})
    answer(owner, info, text="noted")
    assert listed(owner) == []


def test_a_decision_wakes_only_its_computed_audience(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    enable(owner)
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Yes.")
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).one()
    assert ticker_read.wakes(row, team["hub"].id)
    assert not ticker_read.wakes(row, team["admin"].id), "a reader without a reason is not woken"


# --- §17.2 releases ---------------------------------------------------------------------


def test_a_release_card_done_announces_its_version_once(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    enable(owner)
    card = task(owner, kind="release", release={"version": "0.3.0"}, title="First public")
    with migrated.connect() as conn:
        project = conn.execute(select(t.project).where(t.project.c.slug == "maity")).one()
        row = conn.execute(select(t.card).where(t.card.c.id == card["id"])).one()
    for _ in range(2):
        with events.transaction(migrated) as conn:
            ticker.on_release_done(conn, project, row, None, None)
    [item] = listed(owner)
    assert (item["type"], item["text"]) == ("release", "Released 0.3.0: First public")
    raw = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert raw["payload"]["dedupe_key"] == "release:0.3.0"
    assert set(reasons(raw)) == {owner.id, *(a.id for a in team.values())}


# --- §17.5 shaping per reader, waking --------------------------------------------------


def test_only_human_owners_and_admins_see_everyones_reasons(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(owner, to="all", areas=None)
    as_owner = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert len(as_owner["payload"]["reasons"]) == 5
    as_admin_agent = (
        team["admin"].get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    )
    assert [r["member_id"] for r in as_admin_agent["payload"]["reasons"]] == [team["admin"].id]
    assert as_admin_agent["audience"] == ["all", f"member:{team['admin'].id}"]


def test_all_never_wakes_a_ticker_item(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    note(owner, areas=["web/"])
    with migrated.connect() as conn:
        row = conn.execute(select(t.event).where(t.event.c.kind == "ticker")).one()
        hub_row = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == team["hub"].id)
        ).one()
        web_row = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == team["web"].id)
        ).one()
    assert not events.wakes(row, hub_row, team["hub"].id), "readable through all, never woken by it"
    assert events.wakes(row, web_row, team["web"].id)


def test_the_resume_packet_has_the_ticker_for_me_first(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    agent = team["web"]
    cursor = agent.resume().json()["events"]["cursor"]
    note(owner, text="for web", areas=["web/"])
    note(owner, text="for hub", areas=["hub/"])
    packet = agent.resume(cursor=cursor).json()["ticker"]
    assert [i["text"] for i in packet["items"]] == ["for web", "for hub"]
    assert (packet["for_me"], packet["others"], packet["truncated"]) == (1, 1, False)


# --- §17.3 settings.ticker -------------------------------------------------------------


def test_settings_ticker_is_set_beside_the_other_settings(owner: flow.Human) -> None:
    owner.patch("/projects/maity", {"settings": {"release_checklist": ["CHANGELOG"]}})
    enable(
        owner,
        contract_files=["docs/api.md"],
        contract_implementers={"8.2": ["area:hub/"], "*": ["role:admin"]},
    )
    settings = owner.get("/projects/maity").json()["settings"]
    assert settings["release_checklist"] == ["CHANGELOG"], "a setting not named stays"
    assert settings["ticker"]["enabled"] is True
    assert settings["ticker"]["contract_implementers"]["8.2"] == ["area:hub/"]


@pytest.mark.parametrize(
    "ticker_settings",
    [
        {"contract_implementers": {"eight": ["area:hub/"]}},
        {"contract_implementers": {"8": ["hub/"]}},
        {"contract_implementers": {"8": [f"member:a{n}" for n in range(21)]}},
        {"contract_files": [f"f{n}.md" for n in range(11)]},
    ],
)
def test_settings_ticker_is_checked(owner: flow.Human, ticker_settings: dict[str, Any]) -> None:
    response = owner.patch("/projects/maity", {"settings": {"ticker": ticker_settings}})
    assert response.status_code == 400, response.text


def test_an_agent_cannot_switch_the_ticker_on(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    response = team["admin"].patch("/projects/maity", {"settings": {"ticker": {"enabled": True}}})
    assert response.status_code == 403


# --- review round: concurrency, replays, redaction, settings, the decision's rules ----------


def test_one_members_concurrent_changes_all_land(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    from concurrent.futures import ThreadPoolExecutor

    agent = team["web"]
    areas = [f"a{n}/" for n in range(12)]
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(
            pool.map(
                lambda a: agent.patch(
                    "/projects/maity/ticker/subscription", {"add": {"follow": {"areas": [a]}}}
                ),
                areas,
            )
        )
    assert [r.status_code for r in answers] == [200] * len(areas)
    final = agent.get("/projects/maity/ticker/subscription").json()
    assert sorted(final["follow"]["areas"]) == sorted(areas), "nothing read first, nothing lost"


def test_a_replayed_subscription_change_answers_as_the_first_time(owner: flow.Human) -> None:
    body = {"add": {"mute": {"types": ["note"]}}}
    headers = {"X-CSRF-Token": owner.csrf, "Idempotency-Key": "ticker-sub-replay-0001"}
    first = owner.client.patch(
        "/api/v1/projects/maity/ticker/subscription", json=body, headers=headers
    )
    again = owner.client.patch(
        "/api/v1/projects/maity/ticker/subscription", json=body, headers=headers
    )
    assert first.status_code == again.status_code == 200
    assert again.headers.get("Idempotent-Replayed") == "true"
    assert again.json()["mute"]["types"] == ["note"]


def test_humans_are_never_woken_by_an_item(
    owner: flow.Human, team: dict[str, flow.Agent], make_client: ClientFactory, migrated: Engine
) -> None:
    item = note(team["admin"], to="all", areas=None)
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    by = {r["member_id"]: r for r in full["payload"]["reasons"]}
    assert by[owner.id]["wake"] is False, "for me, never a wake (§17.10)"
    assert f"member:{owner.id}" in full["audience"], "listed by its token, never woken"
    assert listed(owner, "?for=me")[0]["seq"] == item["seq"]


def test_a_redacted_item_is_noticed_by_its_audience_shaped_and_wakes_no_one(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    item = note(owner, areas=["web/"])
    redacted = owner.post(
        f"/projects/maity/events/{item['seq']}/redact", {"reason": "wrong project"}
    )
    assert redacted.status_code == 200
    as_hub = team["hub"].get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"]
    tomb = next(e for e in as_hub if e["seq"] == item["seq"])
    assert tomb["redacted"] and tomb["audience"] == ["all"], "the tombstone is shaped like the item"
    as_web = team["web"].get(f"/projects/maity/events?after={item['seq']}").json()["items"]
    [notice] = [e for e in as_web if e["kind"] == "event_redacted"]
    assert notice["audience"] == [
        "all",
        f"member:{team['web'].id}",
    ], "the item's audience, shaped (§8.5)"
    with migrated.connect() as conn:
        web = conn.execute(
            select(t.membership).where(t.membership.c.agent_id == team["web"].id)
        ).one()
        woken, _ = events.read_waking(conn, web.project_id, web, team["web"].id, item["seq"], 50)
    assert woken == [], "noticed, never woken by it"
    [listed_item] = listed(team["web"])
    assert listed_item["redacted"] is True


def test_the_notice_of_a_withheld_decision_is_withheld_too(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    enable(owner)
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Yes.")
    [item] = listed(team["hub"])
    owner.post(f"/projects/maity/events/{item['seq']}/redact", {"reason": "x"})
    seen = team["web"].get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"]
    assert not any(
        e["kind"] == "event_redacted" and e["subject"]["id"] == str(item["seq"]) for e in seen
    )
    asker = team["hub"].get(f"/projects/maity/events?after={item['seq']}").json()["items"]
    assert any(e["kind"] == "event_redacted" for e in asker)


def test_humans_keep_their_token_without_a_wake(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    owner.patch("/projects/maity/ticker/subscription", {"add": {"follow": {"areas": ["web/"]}}})
    item = note(team["admin"], areas=["web/"])
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert f"member:{owner.id}" in full["audience"], "the token that names a human for §18"
    assert {r["member_id"]: r["wake"] for r in full["payload"]["reasons"]}[owner.id] is False


def test_an_agents_own_post_does_not_wake_it(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    item = note(team["admin"], to="all", areas=None)
    full = owner.get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    by = {r["member_id"]: r for r in full["payload"]["reasons"]}
    assert by[team["admin"].id]["wake"] is False and by[team["hub"].id]["wake"] is True


def test_a_release_item_names_the_version_of_its_card(owner: flow.Human, migrated: Engine) -> None:
    enable(owner)
    card = task(owner, kind="release", release={"version": "0.4.0"}, title="Second")
    with migrated.begin() as conn:
        conn.execute(
            t.card.update().where(t.card.c.id == card["id"]).values(release_version="0.0.9")
        )
        project = conn.execute(select(t.project)).one()
        row = conn.execute(select(t.card).where(t.card.c.id == card["id"])).one()
    with events.transaction(migrated) as conn:
        ticker.on_release_done(conn, project, row, None, None)
    [item] = listed(owner)
    assert item["text"] == "Released 0.4.0: Second", "release_data's version first"


def test_hub_and_hub_slash_name_one_area() -> None:
    assert ticker.contains("hub/", "hub") and ticker.contains("hub", "hub/x.py")
    assert not ticker.contains("hub/", "hubs/x.py") and not ticker.contains("hub", "hubx")


def test_a_redacted_decision_is_withheld_like_a_live_one(
    owner: flow.Human, team: dict[str, flow.Agent]
) -> None:
    enable(owner)
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Yes.")
    [item] = listed(team["hub"])
    owner.post(f"/projects/maity/events/{item['seq']}/redact", {"reason": "x"})
    assert listed(team["web"]) == [], "no item and no placeholder (§17.5)"
    assert listed(team["hub"])[0]["redacted"] is True


def test_a_reader_who_lost_access_no_longer_reads_the_decision(
    owner: flow.Human, team: dict[str, flow.Agent], make_client: ClientFactory
) -> None:
    enable(owner)
    proxy = flow.agent(make_client, owner, role="proxy")
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Yes.")
    assert listed(proxy) != [], "a proxy holds requests:answer"
    owner.patch(f"/projects/maity/members/{proxy.id}", {"role": "member"})
    assert listed(proxy) == [], "checked again at read time (§17.5)"


def test_an_answer_in_words_never_appears(owner: flow.Human, team: dict[str, flow.Agent]) -> None:
    enable(owner)
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="a secret reason in words")
    [item] = listed(team["hub"])
    assert item["detail"] == {"request_title": "Which?", "reply_label": None}
    raw = team["hub"].get(f"/projects/maity/events?after={item['seq'] - 1}").json()["items"][0]
    assert "a secret reason in words" not in str(raw)


def test_talk_is_no_decision(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    enable(owner)
    request = asked(team["hub"], to="owner")
    with migrated.begin() as conn:
        conn.execute(
            t.request.update()
            .where(t.request.c.id == request["id"])
            .values(
                status="answered", answer={"reply_id": None, "text": "let's talk", "talk": True}
            )
        )
        project = conn.execute(select(t.project)).one()
        row = conn.execute(select(t.request).where(t.request.c.id == request["id"])).one()
    with events.transaction(migrated) as conn:
        ticker.on_request_answered(conn, project, row, None)
    assert listed(owner) == []


def hold(
    engine: Engine, card_id: str, *, holder: str | None = None, assignee: str | None = None
) -> None:
    """The card's holder and assignee as the decision is answered (asking may block it)."""
    with engine.begin() as conn:
        ids = dict(conn.execute(select(t.membership.c.agent_id, t.membership.c.id)).all())
        conn.execute(
            t.card.update()
            .where(t.card.c.id == card_id)
            .values(claim_holder=ids.get(holder), assigned_to=ids.get(assignee))
        )


def decision_event(owner: flow.Human) -> dict[str, Any]:
    seq = listed(owner)[0]["seq"]
    event: dict[str, Any] = owner.get(f"/projects/maity/events?after={seq - 1}").json()["items"][0]
    return event


def test_the_asker_and_the_card_holder_cannot_mute_a_decision(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine
) -> None:
    enable(owner)
    card = task(team["admin"], title="Hash")
    for agent in (team["hub"], team["admin"]):
        agent.patch(
            "/projects/maity/ticker/subscription", {"add": {"mute": {"types": ["decision"]}}}
        )
    request = asked(team["hub"], to="owner", task_id=card["id"])
    hold(migrated, card["id"], holder=team["admin"].id)
    answer(owner, request, text="Yes.")
    by = reasons(decision_event(owner))
    assert by[team["hub"].id] == ["decision_asker"]
    assert by[team["admin"].id] == [f"card_holder:{card['id']}"]


def test_the_holder_and_the_assignee_both_hear_of_a_decision(
    owner: flow.Human, team: dict[str, flow.Agent], migrated: Engine, make_client: ClientFactory
) -> None:
    enable(owner)
    proxy = flow.agent(make_client, owner, role="proxy")
    card = task(owner, title="Hash")
    request = asked(team["hub"], to="owner", task_id=card["id"])
    hold(migrated, card["id"], holder=team["admin"].id, assignee=proxy.id)
    answer(owner, request, text="Yes.")
    by = reasons(decision_event(owner))
    assert by[team["admin"].id] == [f"card_holder:{card['id']}"]
    assert by[proxy.id] == [f"card_assignee:{card['id']}"]
    assert team["web"].id not in by, "nobody who may not read the request"


def test_a_decisions_followers_are_listed_not_woken_and_only_if_they_may_read(
    owner: flow.Human, team: dict[str, flow.Agent], make_client: ClientFactory
) -> None:
    enable(owner)
    proxy = flow.agent(make_client, owner, role="proxy")
    for agent in (proxy, team["web"]):
        agent.patch(
            "/projects/maity/ticker/subscription", {"add": {"follow": {"types": ["decision"]}}}
        )
    request = asked(team["hub"], to="owner")
    answer(owner, request, text="Yes.")
    raw = owner.get(f"/projects/maity/events?after={listed(owner)[0]['seq'] - 1}").json()["items"][
        0
    ]
    by = {r["member_id"]: r for r in raw["payload"]["reasons"]}
    assert by[proxy.id]["why"] == ["follow:type:decision"] and by[proxy.id]["wake"] is False
    assert team["web"].id not in by, "a follower who may not read the request gets nothing"


def test_the_area_filter_looks_at_paths_too(owner: flow.Human, migrated: Engine) -> None:
    with events.transaction(migrated) as conn:
        project = conn.execute(select(t.project)).one()
        ticker.write(
            conn,
            project.id,
            kind="note",
            text="paths only",
            url=None,
            audience=ticker.Audience(),
            origin="manual",
            facts={"paths": ["hub/maity_hub/claims.py"], "areas": []},
        )
    assert [i["text"] for i in listed(owner, "?area=hub/maity_hub/")] == ["paths only"]
    assert [i["text"] for i in listed(owner, "?area=hub")] == ["paths only"], "hub and hub/ alike"


def test_after_pages_carry_a_cursor_while_more_follow(owner: flow.Human) -> None:
    seqs = [note(owner, text=f"n{n}", areas=["/"])["seq"] for n in range(3)]
    first = owner.get(f"/projects/maity/ticker?after={seqs[0] - 1}&limit=2").json()
    assert [i["seq"] for i in first["items"]] == seqs[:2] and first["next_cursor"]
    second = owner.get(f"/projects/maity/ticker?limit=2&cursor={first['next_cursor']}").json()
    assert [i["seq"] for i in second["items"]] == seqs[2:] and second["next_cursor"] is None


def test_the_packet_counts_every_item(owner: flow.Human, team: dict[str, flow.Agent]) -> None:
    agent = team["web"]
    cursor = agent.resume().json()["events"]["cursor"]
    for n in range(23):
        ticker_routes.POSTS.reset()
        (
            note(owner, text=f"web {n}", areas=["web/"])
            if n % 2
            else note(owner, text=f"hub {n}", areas=["hub/"])
        )
    packet = agent.resume(cursor=cursor).json()["ticker"]
    assert (packet["for_me"], packet["others"], packet["truncated"]) == (11, 12, True)
    assert len(packet["items"]) == 20 and all(i["for_me"] for i in packet["items"][:11])


# --- §6.1 settings, by top-level key ---------------------------------------------------


def test_settings_null_removes_a_key(owner: flow.Human) -> None:
    enable(owner)
    owner.patch("/projects/maity", {"settings": {"ticker": None}})
    assert "ticker" not in owner.get("/projects/maity").json()["settings"]


def test_settings_a_named_key_is_replaced_whole(owner: flow.Human) -> None:
    enable(owner, contract_files=["docs/api.md"])
    owner.patch("/projects/maity", {"settings": {"ticker": {"enabled": False}}})
    assert owner.get("/projects/maity").json()["settings"]["ticker"]["contract_files"] == []


def test_settings_empty_changes_nothing(owner: flow.Human) -> None:
    owner.patch("/projects/maity", {"settings": {"release_checklist": ["CHANGELOG"]}})
    enable(owner)
    before = owner.get("/projects/maity").json()["settings"]
    assert owner.patch("/projects/maity", {"settings": {}}).status_code == 200
    assert owner.get("/projects/maity").json()["settings"] == before
