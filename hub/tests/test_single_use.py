"""The one implementation of single-use mail links (auth/single_use.py), for both of its
tables: `email_sign_in` (auth/email_links.py) and `password_reset` (auth/password_resets.py).
The limiters' names are pinned: they key the shared counts and must never change."""

from __future__ import annotations

import secrets
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, select

from maity_hub import clock, db
from maity_hub import tables as t
from maity_hub.auth import email_links, password_resets, single_use

HUMAN = "hum-single-use"
OTHER = "hum-single-use-other"


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    db.migrate(engine)
    with engine.begin() as connection:
        for human, handle in ((HUMAN, "single-use"), (OTHER, "single-use-other")):
            connection.execute(
                insert(t.human).values(
                    id=human,
                    handle=handle,
                    display_name="Single use",
                    password_hash="not-used",
                    created_at=clock.now(),
                )
            )
        yield connection


def _sign_in_columns() -> dict[str, Any]:
    """What `email_links.issue` adds to a row of its own, with a browser of its own each time
    (`pending_hash` is unique); no code, so no MAC."""
    return {
        "pending_hash": single_use.digest(secrets.token_urlsafe(16)),
        "address_epoch": 1,
        "next_path": "/",
        "code_mac": None,
        "wrong_codes": 0,
    }


KINDS: dict[str, tuple[single_use.Kind, Callable[[], dict[str, Any]]]] = {
    "email_sign_in": (email_links.KIND, _sign_in_columns),
    "password_reset": (password_resets.KIND, lambda: {}),
}


@pytest.fixture(params=sorted(KINDS))
def kind(request: pytest.FixtureRequest) -> tuple[single_use.Kind, Any]:
    return KINDS[request.param]


def issue(
    conn: Connection,
    kind: tuple[single_use.Kind, Any],
    *,
    human_id: str = HUMAN,
    source: str = "192.0.2.1",
    requested_at: Any = None,
) -> tuple[str, Any] | None:
    links, columns = kind
    return single_use.issue(
        conn,
        links,
        human_id=human_id,
        source=source,
        requested_at=requested_at,
        **columns(),
    )


def row(conn: Connection, links: single_use.Kind, nonce: str) -> Any:
    table = links.table
    return conn.execute(select(table).where(table.c.nonce_hash == single_use.digest(nonce))).one()


def test_the_two_kinds_differ_in_table_life_and_cleared_columns_only() -> None:
    sign_in, reset = email_links.KIND, password_resets.KIND
    assert (sign_in.table, sign_in.lifetime, sign_in.cleared) == (
        t.email_sign_in,
        timedelta(minutes=15),
        ("code_mac",),
    )
    assert (reset.table, reset.lifetime, reset.cleared) == (
        t.password_reset,
        timedelta(minutes=30),
        (),
    )
    at = clock.now()
    assert sign_in.spent(at) == {"used_at": at, "code_mac": None}
    assert reset.spent(at) == {"used_at": at}


def test_issue_returns_none_when_a_newer_row_from_the_same_source_exists(
    conn: Connection, kind: tuple[single_use.Kind, Any]
) -> None:
    links = kind[0]
    asked = clock.now()
    newer = issue(conn, kind, requested_at=asked + timedelta(seconds=1))
    assert newer is not None
    assert issue(conn, kind, requested_at=asked) is None
    # Nothing changed: the newer row is still open, and no second row was written.
    assert row(conn, links, newer[0]).used_at is None
    assert len(conn.execute(select(links.table)).all()) == 1
    # Another source is not held back by it.
    assert issue(conn, kind, source="192.0.2.2", requested_at=asked) is not None


def test_issue_returns_none_for_a_request_that_outlived_a_row_s_life(
    conn: Connection, kind: tuple[single_use.Kind, Any]
) -> None:
    links = kind[0]
    assert issue(conn, kind, requested_at=clock.now() - links.lifetime) is None
    assert conn.execute(select(links.table)).all() == []


def test_issue_voids_the_earlier_unused_row_of_the_same_source_only(
    conn: Connection, kind: tuple[single_use.Kind, Any]
) -> None:
    links = kind[0]
    first = issue(conn, kind)
    elsewhere = issue(conn, kind, source="192.0.2.2")
    second = issue(conn, kind)
    assert first is not None and elsewhere is not None and second is not None
    assert row(conn, links, first[0]).used_at is not None
    assert row(conn, links, elsewhere[0]).used_at is None
    fresh = row(conn, links, second[0])
    assert fresh.used_at is None and fresh.source == "192.0.2.1"
    assert fresh.expires_at == second[1]


def test_use_is_single_use(conn: Connection, kind: tuple[single_use.Kind, Any]) -> None:
    links = kind[0]
    issued = issue(conn, kind)
    assert issued is not None
    stored = row(conn, links, issued[0])
    assert single_use.use(conn, links, stored)
    assert not single_use.use(conn, links, stored)
    assert row(conn, links, issued[0]).used_at is not None


def test_use_refuses_an_expired_row(conn: Connection, kind: tuple[single_use.Kind, Any]) -> None:
    links = kind[0]
    start = clock.now()
    issued = issue(conn, kind)
    assert issued is not None
    clock.set_source(lambda: start + links.lifetime)
    assert not single_use.use(conn, links, row(conn, links, issued[0]))


def test_void_human_voids_only_that_human_s_open_rows(
    conn: Connection, kind: tuple[single_use.Kind, Any]
) -> None:
    links = kind[0]
    mine = [issue(conn, kind), issue(conn, kind, source="192.0.2.2")]
    theirs = issue(conn, kind, human_id=OTHER)
    single_use.void_human(conn, links, HUMAN)
    assert all(row(conn, links, issued[0]).used_at is not None for issued in mine if issued)
    assert theirs is not None and row(conn, links, theirs[0]).used_at is None


def test_void_open_voids_every_open_row(
    conn: Connection, kind: tuple[single_use.Kind, Any]
) -> None:
    links = kind[0]
    issued = [issue(conn, kind), issue(conn, kind, human_id=OTHER)]
    single_use.void_open(conn, links)
    assert all(row(conn, links, one[0]).used_at is not None for one in issued if one)


def test_a_spent_sign_in_row_loses_its_code(conn: Connection) -> None:
    # `email_sign_in` clears `code_mac` with `used_at`, at every way a row is spent.
    links = email_links.KIND

    def issue_with_code() -> tuple[str, Any] | None:
        columns = {**_sign_in_columns(), "code_mac": "mac"}
        return single_use.issue(conn, links, human_id=HUMAN, source="192.0.2.1", **columns)

    for spend in (
        lambda stored: single_use.use(conn, links, stored),
        lambda stored: single_use.void_human(conn, links, HUMAN),
        lambda stored: single_use.void_open(conn, links),
        lambda stored: issue_with_code(),  # the next request from the same source
    ):
        issued = issue_with_code()
        assert issued is not None
        assert row(conn, links, issued[0]).code_mac == "mac"
        spend(row(conn, links, issued[0]))
        spent = row(conn, links, issued[0])
        assert spent.used_at is not None and spent.code_mac is None


def test_the_old_module_names_are_the_shared_ones() -> None:
    assert email_links.digest is single_use.digest
    assert email_links.lock_human is single_use.lock_human
    assert email_links.recipient_over is single_use.recipient_over
    assert email_links.RECIPIENT_PER_HOUR == single_use.RECIPIENT_PER_HOUR == 5
    assert email_links.RECIPIENT_PER_DAY == single_use.RECIPIENT_PER_DAY == 20
    assert email_links.RECIPIENT_MAILS_PER_HOUR == single_use.RECIPIENT_MAILS_PER_HOUR == 50
    assert email_links.RECIPIENT_MAILS_PER_DAY == single_use.RECIPIENT_MAILS_PER_DAY == 200


LIMITERS = (
    "by_source",
    "pair_quarter",
    "pair_day",
    "recipient_hour",
    "recipient_day",
    "recipient_hour_networks",
    "recipient_day_networks",
    "recipient_mails_hour",
    "recipient_mails_day",
)


@pytest.mark.parametrize(
    ("limits", "names"),
    [
        (
            email_links.RequestLimits,
            [
                "auth.email_links.by_source",
                "auth.email_links.pair_quarter",
                "auth.email_links.pair_day",
                "auth.email_links.recipient_hour",
                "auth.email_links.recipient_day",
                "auth.email_links.recipient_hour_networks",
                "auth.email_links.recipient_day_networks",
                "auth.email_links.recipient_mails_hour",
                "auth.email_links.recipient_mails_day",
            ],
        ),
        (
            password_resets.RequestLimits,
            [
                "auth.password_resets.by_source",
                "auth.password_resets.pair_quarter",
                "auth.password_resets.pair_day",
                "auth.password_resets.recipient_hour",
                "auth.password_resets.recipient_day",
                "auth.password_resets.recipient_hour_networks",
                "auth.password_resets.recipient_day_networks",
                "auth.password_resets.recipient_mails_hour",
                "auth.password_resets.recipient_mails_day",
            ],
        ),
    ],
)
def test_request_limits_keep_their_names(limits: Any, names: list[str]) -> None:
    # The names key the shared counts (`rate_count`): a rename would reset every count.
    built = limits()
    assert isinstance(built, single_use.RequestLimits)
    assert [getattr(built, attribute).name for attribute in LIMITERS] == names
    assert [limiter.name for limiter in built.recipient()] == names[3:]


def test_request_limits_keep_their_sizes() -> None:
    for limits in (email_links.RequestLimits(), password_resets.RequestLimits()):
        sizes = [
            (getattr(limits, attribute).limit, getattr(limits, attribute).window)
            for attribute in LIMITERS
        ]
        assert sizes == [
            (10, 3600),
            (3, 900),
            (10, 86400),
            (5, 3600),
            (20, 86400),
            (1, 3600),
            (1, 86400),
            (50, 3600),
            (200, 86400),
        ]
