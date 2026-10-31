"""docs/api.md §16.7.2: what the hub counts about the landing page, its variants and the
campaign links: views, registrations, activations, the origin kept with an account, the
statistics and the retention."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select

from maity_hub import campaigns, clock
from maity_hub import tables as t
from tests import flow
from tests.conftest import ClientFactory
from tests.test_landing import GOOD, HERO, text
from tests.test_registration import PASSWORD, pending
from tests.test_registration_accounts import (  # noqa: F401  (fixtures and helpers)
    _fresh,
    claims,
    complete,
    requested,
    settings_for,
)

ADMIN = "/admin/settings/landing"
BROWSER = {
    "sec-fetch-mode": "navigate",
    "sec-fetch-dest": "document",
    "user-agent": "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0",
}
CAMPAIGNS = [{"code": "x-h1-w1", "label": "X, hook 1, week 1"}, {"code": "other", "label": "Other"}]


def page(title: str) -> dict[str, Any]:
    return {"title": title, "description": "d", "sections": [HERO, text(GOOD)]}


@pytest.fixture
def owner(make_client: ClientFactory, migrated: Engine) -> flow.Human:
    return flow.human(make_client, migrated)  # the first human: the instance admin


def configure(owner: flow.Human, **setting: Any) -> None:
    saved = owner.patch(
        ADMIN,
        {
            "enabled": True,
            "default_language": "en",
            "pages": {"en": page("Main")},
            "variants": {"maintainers": {"pages": {"en": page("For maintainers")}}},
            "campaigns": CAMPAIGNS,
            **setting,
        },
    )
    assert saved.status_code == 200, saved.text


def sums(engine: Engine) -> dict[tuple[str, str], tuple[int, int, int]]:
    with engine.connect() as conn:
        return {
            (r.variant, r.campaign): (r.views, r.registrations, r.activations)
            for r in conn.execute(select(t.campaign_count))
        }


def origins(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.campaign_origin)))


# --- views ----------------------------------------------------------------------------------


def test_a_browsers_navigation_to_a_page_counts_one_view_for_its_variant_and_campaign(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    visitor = make_client()
    assert visitor.get("/", headers=BROWSER).status_code == 200
    assert visitor.get("/?c=x-h1-w1", headers=BROWSER).status_code == 200
    visitor.get("/for/maintainers?c=x-h1-w1", headers=BROWSER)
    visitor.get("/for/maintainers?c=x-h1-w1", headers=BROWSER)
    assert sums(migrated) == {
        ("default", ""): (1, 0, 0),
        ("default", "x-h1-w1"): (1, 0, 0),
        ("maintainers", "x-h1-w1"): (2, 0, 0),
    }


@pytest.mark.parametrize(
    "headers",
    [
        {},  # no Fetch Metadata
        {**BROWSER, "sec-fetch-mode": "cors"},
        {**BROWSER, "sec-fetch-dest": "image"},
        {**BROWSER, "user-agent": "Mozilla/5.0 (compatible; Googlebot/2.1)"},
        {**BROWSER, "user-agent": "facebookexternalhit/1.1"},
        {**BROWSER, "user-agent": "Slackbot-LinkExpanding 1.0"},
        {**BROWSER, "user-agent": "Mastodon/4.2 (http.rb)"},
    ],
)
def test_a_crawler_a_fetch_that_is_no_navigation_and_a_bare_request_count_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine, headers: dict[str, str]
) -> None:
    configure(owner)
    answer = make_client().get("/", headers=headers)
    assert answer.status_code == 200
    assert sums(migrated) == {}


def test_a_head_the_public_view_and_a_preview_count_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    visitor = make_client()
    assert visitor.head("/", headers=BROWSER).status_code == 200
    assert visitor.get("/?as=public", headers=BROWSER).status_code == 200
    draft = owner.post("/admin/settings/landing/preview", {"pages": {"en": page("Draft")}})
    owner.client.get(f"{draft.json()['url']}", headers=BROWSER)
    assert sums(migrated) == {}


def test_an_unknown_code_counts_as_none_and_a_removed_variant_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    visitor = make_client()
    visitor.get("/?c=unknown", headers=BROWSER)
    visitor.get("/for/gone", headers=BROWSER)  # the app shell, no view
    assert sums(migrated) == {("default", ""): (1, 0, 0)}


def test_nothing_is_counted_while_neither_is_configured(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner, variants={}, campaigns=[])
    make_client().get("/", headers=BROWSER)
    assert sums(migrated) == {}


# --- the origin on the registration ---------------------------------------------------------


def register(client: Any, address: str, origin: Any) -> Any:
    return client.post(
        "/api/v1/auth/register",
        json={"address": address, "password": PASSWORD, "origin": origin},
    )


def pending_origin(engine: Engine, address: str = "ada@example.com") -> Any:
    return [r for r in pending(engine) if r.address == address][-1].origin


@pytest.mark.parametrize(
    ("given", "kept"),
    [
        (
            {"variant": "maintainers", "campaign": "x-h1-w1"},
            {"variant": "maintainers", "campaign": "x-h1-w1"},
        ),
        ({"variant": "default", "campaign": None}, {"variant": "default", "campaign": None}),
        ({"variant": "gone", "campaign": "x-h1-w1"}, {"variant": "default", "campaign": "x-h1-w1"}),
        (
            {"variant": "maintainers", "campaign": "gone"},
            {"variant": "maintainers", "campaign": None},
        ),
        ({"campaign": "other"}, {"variant": "default", "campaign": "other"}),
        ({"variant": "gone", "campaign": "gone"}, None),
        ({}, None),
        (None, None),
    ],
)
def test_the_origin_is_kept_only_for_the_parts_that_still_exist(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    given: Any,
    kept: Any,
) -> None:
    configure(owner)
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    assert register(client, "ada@example.com", given).status_code == 202
    assert pending_origin(migrated) == kept


def test_an_origin_sent_while_nothing_is_configured_is_dropped(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner, variants={}, campaigns=[])
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    register(client, "ada@example.com", {"variant": "default", "campaign": "x-h1-w1"})
    assert pending_origin(migrated) is None


def test_a_body_that_is_no_origin_is_invalid(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    for bad in ("x", 3, {"variant": 1}, {"extra": "no"}, {"variant": "v" * 81}):
        assert register(client, "ada@example.com", bad).status_code == 400


# --- the registration counted, the origin kept with the account -----------------------------


def test_a_completed_registration_counts_and_keeps_the_origin_with_the_account(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    claims: dict[str, str],  # noqa: F811
) -> None:
    configure(owner)
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    register(client, "ada@example.com", {"variant": "maintainers", "campaign": "x-h1-w1"})
    row = [r for r in pending(migrated) if r.address == "ada@example.com"][-1]
    done = complete(migrated, settings, row.id)
    assert done.kind == "created", done
    assert sums(migrated) == {("maintainers", "x-h1-w1"): (0, 1, 0)}
    [kept] = origins(migrated)
    assert (kept.human_id, kept.variant, kept.campaign) == (done.human_id, "maintainers", "x-h1-w1")


def test_a_removed_campaign_is_still_counted_under_the_origin_the_registration_kept(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    claims: dict[str, str],  # noqa: F811
) -> None:
    configure(owner)
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    register(client, "ada@example.com", {"variant": "maintainers", "campaign": "other"})
    row = [r for r in pending(migrated) if r.address == "ada@example.com"][-1]
    owner.patch(ADMIN, {"campaigns": [CAMPAIGNS[0]]})  # "other" is removed meanwhile
    assert complete(migrated, settings, row.id).kind == "created"
    assert sums(migrated) == {("maintainers", "other"): (0, 1, 0)}
    stats = owner.get("/admin/statistics/campaigns").json()
    assert {"code": "other", "label": None, "removed": True} in stats["campaigns"]


def test_a_registration_completed_after_both_were_emptied_counts_nothing(
    owner: flow.Human,
    make_client: ClientFactory,
    migrated: Engine,
    claims: dict[str, str],  # noqa: F811
) -> None:
    configure(owner)
    settings = settings_for()
    client = make_client(mail=settings.mail, registration=settings.registration)
    register(client, "ada@example.com", {"variant": "maintainers", "campaign": "other"})
    row = [r for r in pending(migrated) if r.address == "ada@example.com"][-1]
    owner.patch(ADMIN, {"variants": {}, "campaigns": []})
    assert complete(migrated, settings, row.id).kind == "created"
    assert sums(migrated) == {} and origins(migrated) == []


# --- the activation -------------------------------------------------------------------------


def seed_origin(engine: Engine, human_id: str, at: datetime | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(
            insert(t.campaign_origin).values(
                human_id=human_id,
                variant="maintainers",
                campaign="x-h1-w1",
                registered_at=at or clock.now(),
            )
        )


def test_the_first_exchange_of_an_agent_counts_one_activation_and_ends_the_origin(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    flow.project(owner)
    seed_origin(migrated, owner.id)
    flow.agent(make_client, owner)
    assert sums(migrated) == {("maintainers", "x-h1-w1"): (0, 0, 1)}
    assert origins(migrated) == []
    flow.agent(make_client, owner)  # a second agent: nothing more, once per account
    assert sums(migrated) == {("maintainers", "x-h1-w1"): (0, 0, 1)}


def test_an_exchange_after_30_days_counts_nothing(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    configure(owner)
    flow.project(owner)
    seed_origin(migrated, owner.id, clock.now() - timedelta(days=31))
    flow.agent(make_client, owner)
    assert sums(migrated) == {} and origins(migrated) == []


# --- retention, export, deletion ------------------------------------------------------------


def test_the_origins_end_after_30_days_and_the_sums_after_400(
    owner: flow.Human, migrated: Engine
) -> None:
    other = flow.human  # noqa: F841  (the second account is made below)
    now = clock.now()
    old = now - timedelta(days=31)
    seed_origin(migrated, owner.id, old)
    with migrated.begin() as conn:
        for day in (now.date() - timedelta(days=401), now.date() - timedelta(days=399)):
            campaigns.count(conn, "default", None, views=1, day=day)
        campaigns.purge(conn)
    assert origins(migrated) == []
    assert [d.day for d in _rows(migrated)] == [now.date() - timedelta(days=399)]


def _rows(engine: Engine) -> list[Any]:
    with engine.connect() as conn:
        return list(conn.execute(select(t.campaign_count)))


# --- the statistics -------------------------------------------------------------------------


def seed_sums(engine: Engine) -> None:
    today = clock.now().date()
    with engine.begin() as conn:
        campaigns.count(conn, "maintainers", "x-h1-w1", views=212, registrations=9, activations=4)
        campaigns.count(conn, "default", None, views=5)
        campaigns.count(conn, "teams", "x-h1-w1", day=today - timedelta(days=1), views=1)
        campaigns.count(conn, "default", None, day=today - timedelta(days=40), views=7)


def test_the_statistics_list_the_rows_of_the_window_newest_day_first(
    owner: flow.Human, migrated: Engine
) -> None:
    configure(owner)
    seed_sums(migrated)
    stats = owner.get("/admin/statistics/campaigns?days=30").json()
    today = clock.now().date().isoformat()
    assert stats["window_days"] == 30 and stats["views_approximate"] is True
    assert stats["variants"][:2] == ["default", "maintainers"] and "teams" in stats["variants"]
    assert [c["code"] for c in stats["campaigns"]] == ["x-h1-w1", "other"]
    assert stats["rows"][0] == {
        "date": today,
        "variant": "default",
        "campaign": None,
        "views": 5,
        "registrations": 0,
        "activations": 0,
    }
    assert {"variant": "maintainers", "campaign": "x-h1-w1", "views": 212}.items() <= stats["rows"][
        1
    ].items()
    assert [r["date"] for r in stats["rows"]] == sorted(
        (r["date"] for r in stats["rows"]), reverse=True
    )
    assert all(
        r["date"] > (clock.now().date() - timedelta(days=30)).isoformat() for r in stats["rows"]
    )
    wide = owner.get("/admin/statistics/campaigns?days=400").json()
    assert len(wide["rows"]) == len(stats["rows"]) + 1


def test_the_statistics_as_csv(owner: flow.Human, migrated: Engine) -> None:
    configure(owner)
    seed_sums(migrated)
    answer = owner.get("/admin/statistics/campaigns?format=csv")
    assert answer.status_code == 200
    assert answer.headers["content-type"].startswith("text/csv")
    assert "attachment" in answer.headers["content-disposition"]
    lines = answer.text.strip().split("\n")
    assert lines[0] == "date,variant,campaign,views,registrations,activations"
    assert f"{clock.now().date().isoformat()},default,,5,0,0" in lines
    assert any(",maintainers,x-h1-w1,212,9,4" in line for line in lines)


@pytest.mark.parametrize("query", ["days=0", "days=401", "days=-1", "format=xml"])
def test_the_statistics_refuse_a_window_or_a_format_out_of_range(
    owner: flow.Human, query: str
) -> None:
    answer = owner.get(f"/admin/statistics/campaigns?{query}")
    assert answer.status_code == 400
    assert answer.json()["error"]["code"] == "invalid"


def test_the_statistics_are_the_admin_s_alone(
    owner: flow.Human, make_client: ClientFactory, migrated: Engine
) -> None:
    other = flow.human(make_client, migrated, "other")
    assert other.get("/admin/statistics/campaigns").status_code == 403
    assert make_client().get("/api/v1/admin/statistics/campaigns").status_code in (401, 403)


def test_counting_twice_on_one_day_adds_to_one_row(migrated: Engine) -> None:
    with migrated.begin() as conn:
        campaigns.count(conn, "default", None, views=1)
        campaigns.count(conn, "default", None, views=2, registrations=1)
    [row] = _rows(migrated)
    assert (row.views, row.registrations, row.activations) == (3, 1, 0)
    assert isinstance(row.day, date) and datetime.now(UTC).date() >= row.day
