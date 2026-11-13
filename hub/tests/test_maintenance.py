"""docs/api.md §16.12: maintenance windows — the admin's routes, the `503 maintenance` with
its exceptions, the broadcast and each owner's choice, and the deadlines that move."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import Engine, insert, select, update

from maity_hub import clock, maintenance
from maity_hub import tables as t
from maity_hub.config import Settings
from maity_hub.notifications.preferences import HELD_FOR
from tests import factory, flow
from tests.conftest import ClientFactory
from tests.statements import count_statements
from tests.test_landing import HERO
from tests.test_registration import SIGNING

START = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)
FROM = START + timedelta(hours=1)
UNTIL = FROM + timedelta(minutes=30)
LENGTH = UNTIL - FROM


class Clock:
    def __init__(self) -> None:
        self.at = START

    def set(self, at: datetime) -> None:
        self.at = at


@pytest.fixture
def now() -> Iterator[Clock]:
    found = Clock()
    clock.set_source(lambda: found.at)
    maintenance.forget()
    yield found
    maintenance.forget()


@pytest.fixture
def admin(make_client: ClientFactory, migrated: Engine, now: Clock) -> flow.Human:
    """The instance admin: the earliest account."""
    return flow.human(make_client, migrated)


def rfc(at: datetime) -> str:
    return clock.rfc3339(at)


def later_human(engine: Engine, now: Clock, handle: str) -> str:
    """Another account, made after the admin's (the earliest account is the instance admin)."""
    at = now.at
    now.set(at + timedelta(seconds=1))
    found = factory.human(engine, handle)
    now.set(at)
    return found


def put(who: flow.Human, starts: datetime = FROM, ends: datetime = UNTIL, text: str = "DB") -> Any:
    return who.client.put(
        "/api/v1/admin/maintenance",
        json={"from": rfc(starts), "until": rfc(ends), "text": text},
        headers={"X-CSRF-Token": who.csrf},
    )


def running(now: Clock, at: datetime = FROM + timedelta(minutes=5)) -> None:
    now.set(at)
    maintenance.forget()


# --- the window and its routes ----------------------------------------------------------


def test_the_admin_sets_changes_and_cancels_a_window(admin: flow.Human, now: Clock) -> None:
    assert admin.get("/maintenance").json() == {"window": None}
    made = put(admin, text="  Database upgrade  ")
    assert made.status_code == 200, made.text
    assert made.json()["window"] | {"by": None} == {
        "from": rfc(FROM),
        "until": rfc(UNTIL),
        "text": "Database upgrade",
        "state": "upcoming",
        "by": None,
        "created_at": rfc(START),
        "updated_at": rfc(START),
    }
    assert made.json()["window"]["by"] == admin.id
    # everyone reads it, without the admin's fields
    assert admin.get("/maintenance").json()["window"] == {
        "from": rfc(FROM),
        "until": rfc(UNTIL),
        "text": "Database upgrade",
        "state": "upcoming",
    }
    now.set(START + timedelta(seconds=1))
    changed = put(admin, ends=UNTIL + timedelta(minutes=10), text="Longer")
    assert changed.status_code == 200, changed.text
    assert changed.json()["window"]["until"] == rfc(UNTIL + timedelta(minutes=10))
    now.set(START + timedelta(seconds=2))
    assert admin.delete("/admin/maintenance").json() == {"window": None}
    assert admin.get("/admin/maintenance").json() == {"window": None}
    actions = [c["action"] for c in admin.get("/admin/maintenance/changes").json()["items"]]
    assert actions == ["cancelled", "changed", "created"]


def test_the_fields_are_checked(admin: flow.Human, now: Clock) -> None:
    refused = put(admin, starts=UNTIL, ends=FROM, text="")
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"]["details"]["fields"] == {
        "text": "too_short",
        "from": "from_after_until",
    }
    late = put(admin, starts=START - timedelta(hours=2), ends=START - timedelta(hours=1))
    assert late.json()["error"]["details"]["fields"]["until"] == "until_past"
    long = put(admin, text="x" * 501)
    assert long.json()["error"]["details"]["fields"] == {"text": "too_long"}
    assert put(admin, text="x" * 500).status_code == 200
    # a running window keeps its `from`, and is ended, not cancelled
    running(now)
    moved = put(admin, starts=FROM + timedelta(minutes=1))
    assert moved.json()["error"]["details"]["fields"] == {"from": "running"}
    assert put(admin, ends=UNTIL + timedelta(minutes=5)).status_code == 200
    gone = admin.delete("/admin/maintenance")
    assert gone.status_code == 409
    assert gone.json()["error"]["code"] == "maintenance_running"


def test_only_the_instance_admin_sets_one(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    now.set(START + timedelta(seconds=1))  # after the admin: the earliest account is the admin
    other = flow.human(make_client, migrated, "other")
    now.set(START)
    assert put(other).status_code == 403
    assert other.get("/admin/maintenance").status_code == 403
    assert other.delete("/admin/maintenance").status_code == 403
    assert other.post("/admin/maintenance/end").status_code == 403
    assert other.get("/admin/maintenance/changes").status_code == 403
    assert admin.get("/maintenance").json() == {"window": None}


def test_ending_early_ends_the_window_now(admin: flow.Human, now: Clock) -> None:
    put(admin)
    assert admin.post("/admin/maintenance/end").json()["error"]["code"] == (
        "maintenance_not_running"
    )
    running(now)
    ended = admin.post("/admin/maintenance/end")
    assert ended.status_code == 200, ended.text
    assert admin.get("/maintenance").json() == {"window": None}
    latest = admin.get("/admin/maintenance/changes").json()["items"][0]
    assert latest["action"] == "ended"
    assert latest["window"]["until"] == rfc(FROM + timedelta(minutes=5))


def test_the_changes_are_paged(admin: flow.Human, now: Clock) -> None:
    for minutes in range(3):
        now.set(START + timedelta(seconds=minutes))
        put(admin, ends=UNTIL + timedelta(minutes=minutes))
    first = admin.get("/admin/maintenance/changes?limit=2").json()
    assert len(first["items"]) == 2 and first["next_cursor"]
    rest = admin.get(f"/admin/maintenance/changes?limit=2&cursor={first['next_cursor']}").json()
    assert [c["action"] for c in rest["items"]] == ["created"]
    assert rest["next_cursor"] is None


# --- the refusal and its exceptions -----------------------------------------------------


def test_a_running_window_refuses_the_api_with_retry_after(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    flow.project(admin, "maity")
    put(admin, text="Upgrade")
    assert admin.get("/projects").status_code == 200  # upcoming: nothing refused
    running(now)
    refused = admin.get("/projects")
    assert refused.status_code == 503, refused.text
    assert refused.headers["Retry-After"] == str(25 * 60)
    error = refused.json()["error"]
    assert error["code"] == "maintenance"
    assert error["details"] == {"from": rfc(FROM), "until": rfc(UNTIL), "text": "Upgrade"}
    assert admin.post("/projects", {"slug": "other", "name": "Other"}).status_code == 503
    # what stays open: health, the window, the admin's routes, sign-in, `GET /me`
    assert admin.get("/health").status_code == 200
    assert admin.get("/maintenance").json()["window"]["state"] == "running"
    assert admin.get("/admin/maintenance").status_code == 200
    assert admin.get("/admin/maintenance/changes").status_code == 200
    assert admin.get("/auth/session").status_code == 200
    # the two reads the sign-in page is drawn from, for a visitor too
    visitor = make_client()
    assert visitor.get("/api/v1/auth/methods").status_code == 200
    assert visitor.get("/api/v1/auth/pages/sign_in").status_code == 200
    assert visitor.get("/api/v1/auth/pages/sign_up").status_code == 503
    me = admin.get("/me")
    assert me.status_code == 200, me.text
    assert me.json()["maintenance"]["state"] == "running"
    assert admin.patch("/me", {"display_name": "Changed"}).status_code == 503
    fresh = make_client()
    signed_in = factory.login_handle(fresh, "maintainer")
    assert signed_in.status_code == 200, signed_in.text
    # the hub's own pages answer a small page, the badge an empty one; the app shell is served
    page = fresh.get("/explore")
    assert page.status_code == 503 and "Maintenance" in page.text
    assert page.headers["Retry-After"] == str(25 * 60)
    badge = fresh.get("/badge/maintainer/maity.svg")
    assert badge.status_code == 503 and badge.content == b""
    assert fresh.get("/settings").status_code == 200
    # signing out stays open: on a shared computer the way out of a session the window holds
    csrf = fresh.get("/api/v1/auth/session").json()["csrf_token"]
    out = fresh.post("/api/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert out.status_code == 200, out.text
    assert fresh.get("/api/v1/auth/session").status_code == 401
    # the window ends by itself at `until`
    now.set(UNTIL)
    maintenance.forget()
    assert admin.get("/projects").status_code == 200


def test_the_root_is_the_shell_for_a_signed_in_reader_and_the_503_page_for_a_visitor(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    page_body = {"title": "Maity", "description": "A hub", "sections": [HERO]}
    landing = admin.patch("/admin/settings/landing", {"enabled": True, "pages": {"en": page_body}})
    put(admin)
    running(now)
    shell = admin.client.get("/")
    assert shell.status_code == 200, shell.text  # the app shows the full page and End now
    assert "js/app.js" in shell.text  # the app shell
    assert landing.status_code == 200, landing.text
    page = make_client().get("/")  # a visitor: the landing page, refused
    assert page.status_code == 503 and "Maintenance" in page.text
    assert page.headers["Retry-After"] == str(25 * 60)
    maintenance.refresh_frame(admin.client.app.state.engine)  # type: ignore[attr-defined]
    framed = make_client().get("/")
    assert framed.status_code == 503 and '<header class="site-header dz">' in framed.text
    assert 'class="product-line"' not in framed.text


def test_the_503_page_stands_in_the_frame_on_the_public_host_and_small_on_the_join_host(
    make_client: ClientFactory, admin: flow.Human, now: Clock, migrated: Engine
) -> None:
    # §16.7.5, §16.12 (tsk-tp97v64vpy5z): the door frame as last read, where its stylesheets are
    # served; the join host serves none of them (§1.1), so its page stays the small one.
    put(admin)
    running(now)
    first = make_client().get("/explore")  # no frame kept yet: the small page, at once
    assert first.status_code == 503 and 'class="product-line"' in first.text
    maintenance.refresh_frame(migrated)
    framed = make_client().get("/explore")
    assert framed.status_code == 503 and '<header class="site-header dz">' in framed.text
    assert 'class="product-line"' not in framed.text
    joined = make_client(base_url="https://join.example", join_url="https://join.example")
    small = joined.get("/join/not-a-token", headers={"Accept": "text/html"})
    assert small.status_code == 503 and "Maintenance" in small.text
    assert "site-header" not in small.text and 'class="product-line"' in small.text


def test_the_503_page_never_waits_for_the_frames_read(
    make_client: ClientFactory, admin: flow.Human, now: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # #1721's review (v5vp): with the pool used up, the frame's read would wait for the pool's
    # timeout. The read is held here until the page has answered; the page does not wait for it.
    put(admin)
    running(now)
    held = threading.Event()
    reads: list[int] = []

    def frame_of(_engine: Engine) -> dict[str, Any]:
        reads.append(1)
        held.wait(10)
        raise TimeoutError("no pooled connection")

    monkeypatch.setattr(maintenance, "frame_of", frame_of)
    try:
        client = make_client()
        started = time.monotonic()
        for _ in range(3):
            page = client.get("/explore")
            assert page.status_code == 503 and 'class="product-line"' in page.text
        assert time.monotonic() - started < 2, "the 503 waited for the frame's read"
        assert len(reads) <= 1  # one read at a time, not one per refused request
    finally:
        held.set()


def test_a_failing_frame_read_is_tried_again_only_after_a_rest(
    migrated: Engine, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # A database that keeps failing costs one read and one warning per RETRY_SECONDS, not one per
    # refused request (#1721's review); a read that works again ends the rest.
    clock_at = [100.0]
    monkeypatch.setattr(maintenance, "monotonic", lambda: clock_at[0])
    reads: list[int] = []

    def failing(_engine: Engine) -> dict[str, Any]:
        reads.append(1)
        raise TimeoutError("no pooled connection")

    monkeypatch.setattr(maintenance, "frame_of", failing)
    monkeypatch.setattr(maintenance, "_in_background", lambda read, engine: read(engine))
    with caplog.at_level("WARNING", logger="maity_hub.maintenance"):
        for _ in range(5):
            assert maintenance.cached_frame(migrated) is None
        assert len(reads) == 1
        clock_at[0] += maintenance.RETRY_SECONDS
        assert maintenance.cached_frame(migrated) is None
        assert len(reads) == 2
    assert sum("could not be read" in r.getMessage() for r in caplog.records) == 2
    monkeypatch.setattr(maintenance, "frame_of", lambda _engine: {"setting": {}})
    clock_at[0] += maintenance.RETRY_SECONDS
    maintenance.cached_frame(migrated)  # the read that works again
    assert maintenance.cached_frame(migrated) == {"setting": {}}


def test_a_window_does_not_refuse_once_it_is_over_inside_the_cache(
    admin: flow.Human, now: Clock
) -> None:
    put(admin)
    running(now)
    assert admin.get("/projects").status_code == 503
    now.set(UNTIL + timedelta(seconds=1))  # the cached read is a moment old
    assert admin.get("/projects").status_code == 200


def test_a_replica_reads_a_window_set_elsewhere_once_its_cache_is_old(
    admin: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The cache holds for `CACHE_SECONDS` on the cache's own clock, then the window is read
    again: a window another replica set (no `forget` here) reaches this one."""
    assert admin.get("/maintenance").json()["window"] is None
    with migrated.begin() as conn:  # as another replica would
        conn.execute(
            insert(t.maintenance_window).values(
                id="mnt-elsewhere",
                starts_at=FROM,
                ends_at=UNTIL,
                text="elsewhere",
                created_by=admin.id,
                created_at=START,
                updated_by=admin.id,
                updated_at=START,
            )
        )
    assert maintenance.window_now(migrated) is None  # cached
    base = maintenance.monotonic()
    monkeypatch.setattr(maintenance, "monotonic", lambda: base + maintenance.CACHE_SECONDS + 1)
    found = maintenance.window_now(migrated)
    assert found is not None and found["text"] == "elsewhere"


def test_a_slow_runner_does_not_change_what_a_request_costs(
    admin: flow.Human, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """tsk-aaprca1rs4ny: real time (`time.monotonic`) moving 6 s between two measurements
    (a slow CI runner) must not add the window's read to the second one."""
    flow.project(admin, "maity")

    def call() -> None:
        assert admin.get("/projects").status_code == 200

    call()
    few = count_statements(migrated, call)
    wall = time.monotonic() + 6
    monkeypatch.setattr(time, "monotonic", lambda: wall)
    many = count_statements(migrated, call)
    assert many == few, (few, many)


# --- the broadcast and the owner's choice -----------------------------------------------


def broadcasts(engine: Engine) -> list[tuple[str, str, list[str]]]:
    with engine.begin() as conn:
        rows = conn.execute(
            select(t.event.c.kind, t.event.c.project_id, t.event.c.audience)
            .where(t.event.c.kind.like("maintenance_%"))
            .order_by(t.event.c.seq)
        ).all()
    return [(r.kind, r.project_id, sorted(r.audience)) for r in rows]


def test_the_broadcast_reaches_the_agents_their_owners_accept(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    flow.project(admin, "quiet")  # no agent member: no event
    one = flow.agent(make_client, admin)
    two = flow.agent(make_client, admin)
    put(admin)
    assert broadcasts(migrated) == [
        ("maintenance_scheduled", project_id, sorted([f"member:{one.id}", f"member:{two.id}"]))
    ]
    agents = [p["id"] for p in admin.get("/agents").json()["items"]]
    assert admin.get("/me/broadcasts").json() == {"mode": "accept_all", "agents": []}
    chosen = admin.patch("/me/broadcasts", {"mode": "refuse_for", "agents": [agents[0]]})
    assert chosen.status_code == 200, chosen.text
    admin.delete("/admin/maintenance")
    kind, _, audience = broadcasts(migrated)[-1]
    assert kind == "maintenance_cancelled"
    left = [m for m in (one, two) if f"member:{m.id}" in audience]
    assert len(left) == 1
    admin.patch("/me/broadcasts", {"mode": "refuse_all"})
    put(admin)
    assert broadcasts(migrated)[-1][0] == "maintenance_cancelled"  # nobody left to tell


def test_the_choice_is_checked(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    flow.project(admin, "maity")
    flow.agent(make_client, admin)
    now.set(START + timedelta(seconds=1))  # after the admin: the earliest account is the admin
    other = flow.human(make_client, migrated, "other")
    now.set(START)
    flow.project(other, "theirs")
    flow.agent(make_client, other, "other/theirs")
    theirs = other.get("/agents").json()["items"][0]["id"]
    for body, field, code in (
        ({"mode": "sometimes"}, "mode", "invalid"),
        ({"mode": "accept_all", "agents": [theirs]}, "agents", "not_allowed"),
        ({"mode": "accept_only", "agents": [theirs]}, "agents", "not_your_agent"),
    ):
        refused = admin.patch("/me/broadcasts", body)
        assert refused.status_code == 400, refused.text
        assert refused.json()["error"]["details"]["fields"][field] == code
    assert admin.get("/me/broadcasts").json() == {"mode": "accept_all", "agents": []}


# --- the deadlines -----------------------------------------------------------------------


def owner_membership(engine: Engine, project_id: str, human_id: str) -> int:
    with engine.begin() as conn:
        found: int = conn.execute(
            select(t.membership.c.id).where(
                t.membership.c.project_id == project_id, t.membership.c.human_id == human_id
            )
        ).scalar_one()
    return found


def lease(engine: Engine, card_id: str) -> datetime:
    with engine.begin() as conn:
        found: datetime = conn.execute(
            select(t.card.c.lease_until).where(t.card.c.id == card_id)
        ).scalar_one()
    return found.astimezone(UTC)


def leased_cards(engine: Engine, project_id: str, member: int) -> dict[str, str]:
    """A card per position of its lease around the window."""
    found = {}
    for name, at in (
        ("before", FROM - timedelta(seconds=1)),
        ("at_from", FROM),
        ("inside", FROM + timedelta(minutes=10)),
        ("at_until", UNTIL),
        ("margin", UNTIL + timedelta(seconds=60)),
        ("after", UNTIL + timedelta(seconds=61)),
    ):
        found[name] = factory.card(engine, project_id, member, status="in_progress", lease_until=at)
    return found


def test_the_deadlines_in_the_window_and_the_minute_after_move_by_its_length(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    member = owner_membership(migrated, project_id, admin.id)
    cards = leased_cards(migrated, project_id, member)
    put(admin)
    running(now)
    assert lease(migrated, cards["inside"]) == FROM + timedelta(minutes=10)  # not yet
    now.set(UNTIL + timedelta(seconds=30))
    assert admin.get("/maintenance").json() == {"window": None}
    moved = {name: lease(migrated, card) for name, card in cards.items()}
    assert moved == {
        "before": FROM - timedelta(seconds=1),
        "at_from": FROM,
        "inside": FROM + timedelta(minutes=10) + LENGTH,
        "at_until": UNTIL + LENGTH,
        "margin": UNTIL + timedelta(seconds=60) + LENGTH,
        "after": UNTIL + timedelta(seconds=61),
    }
    # once: a second read moves nothing more
    admin.get("/maintenance")
    assert lease(migrated, cards["inside"]) == FROM + timedelta(minutes=10) + LENGTH


def test_a_sweep_before_any_request_finds_the_deadlines_moved(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    member = owner_membership(migrated, project_id, admin.id)
    card = factory.card(
        migrated, project_id, member, status="in_progress", lease_until=UNTIL - timedelta(seconds=1)
    )
    put(admin)
    running(now)
    assert maintenance.running_now(migrated)  # a sweep asks during the window: it waits
    now.set(UNTIL + timedelta(seconds=2))  # still inside the cache's few seconds, no request
    assert not maintenance.running_now(migrated)  # the sweep's own question settles first
    assert lease(migrated, card) == UNTIL - timedelta(seconds=1) + LENGTH


def test_an_early_end_moves_by_the_time_it_ran(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    member = owner_membership(migrated, project_id, admin.id)
    card = factory.card(
        migrated, project_id, member, status="in_progress", lease_until=FROM + timedelta(minutes=8)
    )
    running(now, FROM + timedelta(minutes=10))
    # the window was set before it ran
    now.set(START)
    put(admin)
    running(now, FROM + timedelta(minutes=10))
    admin.post("/admin/maintenance/end")
    assert lease(migrated, card) == FROM + timedelta(minutes=18)


def test_a_cancelled_window_moves_nothing(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    member = owner_membership(migrated, project_id, admin.id)
    card = factory.card(
        migrated, project_id, member, status="in_progress", lease_until=FROM + timedelta(minutes=8)
    )
    put(admin)
    admin.delete("/admin/maintenance")
    now.set(UNTIL + timedelta(minutes=5))
    admin.get("/maintenance")
    assert lease(migrated, card) == FROM + timedelta(minutes=8)


def test_every_listed_deadline_moves_and_closed_ones_do_not(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    inside = FROM + timedelta(minutes=10)
    project_id = flow.project(admin, "maity")["id"]
    bot = factory.agent(migrated, project_id, admin.id)
    other = factory.agent(migrated, project_id, admin.id, instance="b2c3")
    confirmed = factory.agent(migrated, project_id, admin.id, instance="c3d4")
    card = factory.card(migrated, project_id, bot.membership_id)
    pending = later_human(migrated, now, "pending")
    active = later_human(migrated, now, "active")
    made_org = admin.post("/orgs", {"handle": "oz-team", "display_name": "OZ"})
    assert made_org.status_code == 201, made_org.text
    org_id = made_org.json()["id"]
    with migrated.begin() as conn:
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == bot.credential_id)
            .values(ktw_acknowledge_by=inside)
        )
        conn.execute(
            update(t.credential)
            .where(t.credential.c.id == confirmed.credential_id)
            .values(ktw_acknowledge_by=inside, ktw_acknowledged_at=START)
        )
        for status, takeover_id in (("open", "tko-open"), ("released", "tko-closed")):
            conn.execute(
                insert(t.takeover).values(
                    id=takeover_id,
                    project_id=project_id,
                    task_id=card,
                    from_member=bot.membership_id,
                    to_member=other.membership_id,
                    reason="r",
                    status=status,
                    window_minutes=30,
                    window_ends_at=inside,
                    created_at=START,
                )
            )
        for invitation_id, used in (("inv-open", None), ("inv-used", START)):
            conn.execute(
                insert(t.invitation).values(
                    id=invitation_id,
                    project_id=project_id,
                    role="member",
                    trust="member",
                    token_hash=invitation_id.ljust(64, "0"),
                    created_by=admin.id,
                    created_at=START,
                    expires_at=inside,
                    used_at=used,
                )
            )
        for org_invitation_id, closed in (("oin-open", None), ("oin-closed", START)):
            conn.execute(
                insert(t.org_invitation).values(
                    id=org_invitation_id,
                    org_id=org_id,
                    handle=org_invitation_id,
                    role="member",
                    invited_by=admin.id,
                    created_at=START,
                    expires_at=inside,
                    closed_at=closed,
                )
            )
        for human_id, status in ((pending, "pending"), (active, "active")):
            conn.execute(
                insert(t.account_registration).values(
                    human_id=human_id, created_at=START, expires_at=inside, status=status
                )
            )
        change = {
            "id": "adc-1",
            "address": "new@example.org",
            "requested_at": rfc(inside - HELD_FOR),
        }
        conn.execute(
            insert(t.notification_settings).values(
                human_id=pending,
                preferences={},
                address_status="none",
                address_change=change,
                epoch=0,
                hard_failures=0,
                updated_at=START,
            )
        )
    assert put(admin).status_code == 200
    now.set(UNTIL + timedelta(minutes=5))
    admin.get("/maintenance")
    later = inside + LENGTH
    with migrated.begin() as conn:

        def one(column: Any, *where: Any) -> datetime:
            found: datetime = conn.execute(select(column).where(*where)).scalar_one()
            return found.astimezone(UTC)

        assert one(t.credential.c.ktw_acknowledge_by, t.credential.c.id == bot.credential_id) == (
            later
        )
        confirmed_by = one(
            t.credential.c.ktw_acknowledge_by, t.credential.c.id == confirmed.credential_id
        )
        assert confirmed_by == inside  # confirmed already: nothing to move
        assert one(t.takeover.c.window_ends_at, t.takeover.c.id == "tko-open") == later
        assert one(t.takeover.c.window_ends_at, t.takeover.c.id == "tko-closed") == inside
        assert one(t.invitation.c.expires_at, t.invitation.c.id == "inv-open") == later
        assert one(t.invitation.c.expires_at, t.invitation.c.id == "inv-used") == inside
        assert one(t.org_invitation.c.expires_at, t.org_invitation.c.id == "oin-open") == later
        assert one(t.org_invitation.c.expires_at, t.org_invitation.c.id == "oin-closed") == inside
        registration = t.account_registration.c
        assert one(registration.expires_at, registration.human_id == pending) == later
        assert one(registration.expires_at, registration.human_id == active) == inside
        held = conn.execute(
            select(t.notification_settings.c.address_change).where(
                t.notification_settings.c.human_id == pending
            )
        ).scalar_one()
    assert held["requested_at"] == rfc(later - HELD_FOR)


def test_a_round_s_step_deadlines_move() -> None:
    steps: list[dict[str, Any]] = [
        {"name": "answers", "closes_at": rfc(FROM + timedelta(minutes=1)), "closed_at": None},
        {"name": "report", "closes_at": rfc(UNTIL + timedelta(minutes=2)), "closed_at": None},
        {"name": "open"},
        # closed before the window: its deadline is history, not moved
        {"name": "done", "closes_at": rfc(FROM + timedelta(minutes=2)), "closed_at": rfc(FROM)},
    ]
    moved = maintenance._shifted_steps(steps, FROM, UNTIL, LENGTH)
    assert moved == [
        {**steps[0], "closes_at": rfc(FROM + timedelta(minutes=1) + LENGTH)},
        steps[1],
        steps[2],
        steps[3],
    ]
    assert maintenance._shifted_steps(steps[1:], FROM, UNTIL, LENGTH) is None


def test_only_an_open_round_s_deadlines_move(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    project_id = flow.project(admin, "maity")["id"]
    inside = FROM + timedelta(minutes=10)
    with migrated.begin() as conn:
        for round_id, status in (
            ("jfr-answering", "answering"),
            ("jfr-reporting", "reporting"),
            ("jfr-reported", "reported"),
        ):
            conn.execute(
                insert(t.jour_fixe_round).values(
                    id=round_id,
                    project_id=project_id,
                    status=status,
                    trigger="manual",
                    scheduled_for=START,
                    answers_close_at=inside,
                    report_due_at=inside,
                    steps=[],
                    invited=[],
                    absent=[],
                    answers_received=0,
                    posts=[],
                    created_at=START,
                )
            )
    assert put(admin).status_code == 200
    now.set(UNTIL + timedelta(minutes=5))
    admin.get("/maintenance")
    rounds = t.jour_fixe_round.c
    with migrated.begin() as conn:
        found = {
            r.id: (r.answers_close_at.astimezone(UTC), r.report_due_at.astimezone(UTC))
            for r in conn.execute(select(rounds.id, rounds.answers_close_at, rounds.report_due_at))
        }
    later = inside + LENGTH
    assert found == {
        "jfr-answering": (later, inside),  # answering: its answers' close, not the report yet
        "jfr-reporting": (inside, later),
        "jfr-reported": (inside, inside),
    }


def test_a_substitution_s_grace_moves_by_where_it_ends(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    """The grace (15 minutes by default) runs from the outage's start: what counts is where it
    ends, not where the outage began."""
    project_id = flow.project(admin, "maity")["id"]
    starts = {
        "before": FROM - timedelta(minutes=5),  # grace ends inside: moves
        "late": UNTIL - timedelta(minutes=1),  # began inside, grace ends 14 min after: stays
        "covered": FROM - timedelta(minutes=5),  # the policy acted already: stays
    }
    bots = {name: factory.agent(migrated, project_id, admin.id) for name in starts}
    with migrated.begin() as conn:
        for name, at in starts.items():
            conn.execute(
                update(t.membership)
                .where(t.membership.c.id == bots[name].membership_id)
                .values(outage_since=at, cover_state="covered" if name == "covered" else None)
            )
    assert put(admin).status_code == 200
    now.set(UNTIL + timedelta(minutes=5))
    admin.get("/maintenance")
    with migrated.begin() as conn:
        found = {
            name: conn.execute(
                select(t.membership.c.outage_since).where(t.membership.c.id == bot.membership_id)
            )
            .scalar_one()
            .astimezone(UTC)
            for name, bot in bots.items()
        }
    assert found == {
        "before": starts["before"] + LENGTH,
        "late": starts["late"],
        "covered": starts["covered"],
    }


@pytest.mark.parametrize(
    "module",
    [
        "availability",
        "commitment",
        "jourfixe.worker",
        "not_listening",
        "not_listening_digest",
        "org_invitations",
        "registration_accounts",
        "takeovers",
    ],
)
def test_every_deadline_sweep_waits_while_a_window_runs(
    module: str, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import importlib

    from maity_hub import worker_runs

    found = importlib.import_module(f"maity_hub.{module}")
    args = (migrated, None) if module == "registration_accounts" else (migrated,)
    worker = found.Worker(*args, interval=0)
    if hasattr(worker, "_due"):
        worker._due = clock.now() - timedelta(hours=1)  # the digest's hour has come
    asked: list[bool] = []
    swept: list[bool] = []

    def running(engine: Engine) -> bool:
        asked.append(True)
        worker._stop.set()  # one pass only
        return True

    def claimed(*args: Any, **kwargs: Any) -> Any:
        swept.append(True)  # the worker catches what is raised here: say it and stop
        worker._stop.set()
        raise RuntimeError("swept during a window")

    monkeypatch.setattr(maintenance, "running_now", running)
    monkeypatch.setattr(worker_runs, "claim", claimed)
    worker._run()
    assert asked == [True] and swept == []


# --- `/me` and the resume packet ---------------------------------------------------------


def test_me_and_the_packet_carry_the_window(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    flow.project(admin, "maity")
    bot = flow.agent(make_client, admin)
    assert admin.get("/me").json()["maintenance"] is None
    assert bot.resume().json()["maintenance"] is None
    put(admin, text="Upgrade")
    maintenance.forget()
    window = {"from": rfc(FROM), "until": rfc(UNTIL), "text": "Upgrade", "state": "upcoming"}
    assert admin.get("/me").json()["maintenance"] == window
    assert bot.resume().json()["maintenance"] == window


def test_the_export_carries_the_broadcast_choice(
    make_client: ClientFactory, admin: flow.Human
) -> None:
    flow.project(admin, "maity")
    flow.agent(make_client, admin)
    assert admin.get("/me/export").json()["account"]["broadcasts"] == {
        "mode": "accept_all",
        "agents": [],
    }
    agent_id = admin.get("/agents").json()["items"][0]["id"]
    admin.patch("/me/broadcasts", {"mode": "accept_only", "agents": [agent_id]})
    from maity_hub.routes import me

    me.EXPORTS.reset()  # at most one export per 10 minutes
    assert admin.get("/me/export").json()["account"]["broadcasts"] == {
        "mode": "accept_only",
        "agents": [agent_id],
    }


def test_a_stored_public_page_answers_the_503_page_to_a_visitor(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    from tests.test_public_pages import PATH, store

    client = make_client(public_pages=True)
    store(migrated)
    assert client.get(PATH).status_code == 200
    put(admin)
    running(now)
    for query in ("", "?as=public"):  # inside the shell, and bare
        page = client.get(PATH + query)
        assert page.status_code == 503 and "Maintenance" in page.text
        assert page.headers["Retry-After"] == str(25 * 60)
    # Once a frame is kept, in the frame of §16.7.5 like every page of the public host (#1721).
    maintenance.refresh_frame(migrated)
    for query in ("", "?as=public"):
        page = client.get(PATH + query)
        assert page.status_code == 503 and '<header class="site-header dz">' in page.text
        assert 'class="product-line"' not in page.text


@pytest.fixture
def real_shell(web_dir: Path) -> Path:
    """A shell with `<main id="main">`, as web/index.html has it: a stored page then comes
    inside the shell for a visitor (§16.9)."""
    (web_dir / "index.html").write_text(
        '<!doctype html><html><head><meta charset="utf-8"><title>dashboard</title></head>'
        '<body><main id="main"></main><script src="js/app.js"></script></body></html>'
    )
    return web_dir


def test_a_public_page_inside_the_shell_is_refused_too(
    real_shell: Path, make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    from tests.test_public_pages import PATH, store

    client = make_client(public_pages=True)
    store(migrated)
    before = client.get(PATH)
    assert before.status_code == 200 and 'id="main"' in before.text  # inside the shell
    put(admin)
    running(now)
    assert client.get(PATH).status_code == 503


def test_the_legal_pages_stay_readable_during_a_window(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    from tests.test_legal import EN
    from tests.test_legal import PATH as LEGAL

    assert admin.patch(LEGAL, {"imprint": EN}).status_code == 200
    put(admin)
    running(now)
    assert make_client().get("/impressum").status_code == 200


# --- the banner of the hub's own pages ---------------------------------------------------

BANNER = "Maintenance 2026-11-02 13:00–2026-11-02 13:30 UTC: DB &amp; mail"


def test_the_landing_page_carries_the_banner_of_an_upcoming_window(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    page_body = {"title": "Maity", "description": "A hub", "sections": [HERO]}
    assert (
        admin.patch(
            "/admin/settings/landing", {"enabled": True, "pages": {"en": page_body}}
        ).status_code
        == 200
    )
    visitor = make_client()
    assert "maintenance-banner" not in visitor.get("/").text
    put(admin, text="DB & mail")  # escaped
    got = visitor.get("/")
    assert got.status_code == 200
    assert BANNER in got.text
    assert got.text.index("maintenance-banner") < got.text.index("<h1")  # first in the body


def test_a_stored_page_s_tag_follows_the_window(
    make_client: ClientFactory, migrated: Engine, admin: flow.Human, now: Clock
) -> None:
    """A reader's cache must not keep the page without the banner, or with it after the window
    is gone: the tag changes with it, so a conditional request gets the page again."""
    from tests.test_public_pages import PATH, store

    client = make_client(public_pages=True)
    store(migrated)
    plain = client.get(PATH + "?as=public")
    assert "maintenance-banner" not in plain.text
    put(admin, text="DB & mail")
    again = client.get(PATH + "?as=public", headers={"If-None-Match": plain.headers["etag"]})
    assert again.status_code == 200 and BANNER in again.text
    assert again.headers["etag"] != plain.headers["etag"]
    unchanged = client.get(PATH + "?as=public", headers={"If-None-Match": again.headers["etag"]})
    assert unchanged.status_code == 304
    admin.delete("/admin/maintenance")
    after = client.get(PATH + "?as=public", headers={"If-None-Match": again.headers["etag"]})
    assert after.status_code == 200 and "maintenance-banner" not in after.text
    assert after.headers["etag"] == plain.headers["etag"]


def test_the_sign_in_page_offers_no_registration_while_a_window_runs(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    """Registration is refused in a running window (§16.12), so `GET /auth/methods`, which
    stays open, does not offer a way in that ends in a 503 (§2.7)."""
    env = Settings.from_env(
        {
            "MAITY_DATABASE_URL": "sqlite://",
            "MAITY_REGISTRATION": "open",
            "MAITY_MAIL_SIGNING_KEY": SIGNING,
            "MAITY_SMTP_HOST": "smtp.example.com",
            "MAITY_SMTP_FROM": "hub@example.com",
        }
    )
    visitor = make_client(mail=env.mail, registration=env.registration)
    assert visitor.get("/api/v1/auth/methods").json()["registration"] is True
    put(admin)
    maintenance.forget()
    assert visitor.get("/api/v1/auth/methods").json()["registration"] is True  # upcoming
    running(now)
    answer = visitor.get("/api/v1/auth/methods")
    assert answer.status_code == 200, answer.text
    assert answer.json()["registration"] is False
    assert visitor.get("/api/v1/auth/pages/sign_up").status_code == 503
    now.set(UNTIL + timedelta(seconds=1))  # over: the way in is offered again
    assert visitor.get("/api/v1/auth/methods").json()["registration"] is True


def test_the_explore_page_carries_the_banner_of_an_upcoming_window(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    """`/explore` has no `ETag`; the banner is in every answer and lags by `max-age=60` at most."""
    visitor = make_client(public_pages=True)
    assert "maintenance-banner" not in visitor.get("/explore").text
    put(admin, text="DB & mail")
    got = visitor.get("/explore")
    assert got.status_code == 200, got.text
    assert BANNER in got.text
    assert got.headers["Cache-Control"] == "public, max-age=60"


def test_a_legal_page_carries_the_banner_while_the_window_runs(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    from tests.test_legal import EN
    from tests.test_legal import PATH as LEGAL

    admin.patch(LEGAL, {"imprint": EN})
    put(admin, text="DB & mail")
    running(now)
    got = make_client().get("/impressum")
    assert got.status_code == 200 and BANNER in got.text


def test_the_frame_of_the_public_pages_is_refused_too(
    make_client: ClientFactory, admin: flow.Human, now: Clock
) -> None:
    """§16.7.5: during a window `GET /site/chrome` answers `503 maintenance`, and the dashboard
    draws sign-in and sign-up without the frame."""
    visitor = make_client()
    assert visitor.get("/api/v1/site/chrome").status_code == 200
    put(admin, text="Upgrade")
    running(now)
    refused = visitor.get("/api/v1/site/chrome")
    assert refused.status_code == 503 and refused.json()["error"]["code"] == "maintenance"
