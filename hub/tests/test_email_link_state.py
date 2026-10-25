"""Single-use and guess budgets before wiring mail delivery and HTTP routes."""

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, db
from maity_hub import tables as t
from maity_hub.auth import email_links as links

KEY = b"test-mail-key-not-a-live-secret"
HUMAN = "hum-email-state"


@pytest.fixture
def conn(engine: Engine) -> Iterator[Connection]:
    db.migrate(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(t.human).values(
                id=HUMAN,
                handle="mail-state",
                display_name="Mail state",
                password_hash="not-used",
                created_at=clock.now(),
            )
        )
        yield connection


def issue(
    conn: Connection, pending: str = "browser-one", source: str = "192.0.2.1"
) -> links.Issued:
    return links.issue(
        conn,
        human_id=HUMAN,
        address_epoch=1,
        pending=pending,
        source=source,
        next_path="/",
        signing_key=KEY,
    )


def test_code_and_link_are_the_same_single_use_grant(conn: Connection) -> None:
    issued = issue(conn)
    row = links.live(conn, pending="browser-one")
    assert links.live(conn, pending="other-browser") is None
    assert links.try_code(conn, row, issued.code or "", KEY)
    assert links.live(conn, nonce_hash=links.digest(issued.nonce)) is None
    assert not links.use(conn, row)


def test_reading_a_link_does_not_consume_it(conn: Connection) -> None:
    issued = issue(conn)
    row = links.live(conn, nonce_hash=links.digest(issued.nonce))
    assert links.live(conn, nonce_hash=row.nonce_hash) == row
    assert links.use(conn, row)
    assert not links.try_code(conn, row, issued.code or "", KEY)


def test_new_request_only_voids_same_source(conn: Connection) -> None:
    first = issue(conn)
    elsewhere = issue(conn, "browser-two", "192.0.2.2")
    issue(conn, "browser-three")
    assert links.live(conn, nonce_hash=links.digest(first.nonce)) is None
    assert links.live(conn, nonce_hash=links.digest(elsewhere.nonce)) is not None


def test_five_wrong_codes_leave_the_link_live(conn: Connection) -> None:
    issued = issue(conn)
    for _ in range(5):
        row = links.live(conn, pending="browser-one")
        assert not links.try_code(conn, row, "wrong", KEY)
    row = links.live(conn, pending="browser-one")
    assert not links.try_code(conn, row, issued.code or "", KEY)
    assert links.use(conn, row)


def test_twenty_wrong_codes_void_all_codes_but_no_links(conn: Connection) -> None:
    grants = []
    for n in range(5):
        grant = issue(conn, f"browser-{n}", f"192.0.2.{n}")
        grants.append(grant)
    for n in range(4):
        for _ in range(5):
            row = links.live(conn, pending=f"browser-{n}")
            assert not links.try_code(conn, row, "wrong", KEY)
    last = links.live(conn, pending="browser-4")
    assert not links.try_code(conn, last, grants[-1].code or "", KEY)
    assert links.use(conn, last)
    assert issue(conn, "after-budget", "192.0.2.8").code is None
    for grant in grants[:-1]:
        assert links.live(conn, nonce_hash=links.digest(grant.nonce)) is not None


def test_expiry_and_account_void_end_both_ways(conn: Connection) -> None:
    grant = issue(conn)
    conn.execute(update(t.email_sign_in).values(expires_at=clock.now() - timedelta(seconds=1)))
    assert links.live(conn, nonce_hash=links.digest(grant.nonce)) is None
    grant = issue(conn, "next-browser")
    links.void_human(conn, HUMAN)
    assert links.live(conn, nonce_hash=links.digest(grant.nonce)) is None


def test_code_proof_is_bound_to_its_flow_and_key(conn: Connection) -> None:
    grant = issue(conn)
    row = links.live(conn, pending="browser-one")
    assert not links.try_code(conn, row, grant.code or "", b"other-key")
    stored = conn.execute(select(t.email_sign_in)).one()
    assert stored.nonce_hash != grant.nonce
    assert stored.code_mac != grant.code
    assert links.code_mac(KEY, row.nonce_hash, grant.code or "") != links.code_mac(
        KEY, "other", grant.code or ""
    )


@pytest.mark.parametrize("value", ["１２３４５６", "12345", "1234567", "123\t456", "123\n456"])
def test_code_is_six_ascii_digits_with_spaces_only(value: str) -> None:
    assert links.normalise_code(value) is None
    assert links.normalise_code("012 345") == "012345"


def test_stale_read_cannot_bypass_the_fifth_guess(conn: Connection) -> None:
    grant = issue(conn)
    stale = links.live(conn, pending="browser-one")
    for _ in range(5):
        assert not links.try_code(conn, stale, "wrong", KEY)
    assert not links.try_code(conn, stale, grant.code or "", KEY)
    assert links.live(conn, nonce_hash=links.digest(grant.nonce)) is not None


def test_new_utc_day_restores_code_budget(conn: Connection) -> None:
    start = clock.now()
    issue(conn)
    conn.execute(update(t.email_sign_in_day).values(wrong_codes=20))
    assert issue(conn, "blocked").code is None
    clock.set_source(lambda: start + timedelta(days=1))
    assert issue(conn, "tomorrow").code is not None


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize("code", [None, "012345"])
def test_mail_contains_only_the_signin_link_and_optional_code(
    language: str, code: str | None
) -> None:
    link = "https://hub.example/mail/sign-in/signed-token"
    body = links.mail_body(
        language=language,
        display_name="Human",
        link=link,
        code=code,
        requested_at="2026-10-25T06:00:00Z",
        browser="Firefox",
        system="Linux",
        address="192.0.2.1",
    )
    assert body.count("https://") == 1
    assert link in body
    assert "Firefox" in body and "Linux" in body and "192.0.2.1" in body
    assert ("012 345" in body) == (code is not None)
    assert "unsubscribe" not in body


def test_parallel_link_and_code_make_only_one_grant(engine: Engine) -> None:
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    db.migrate(engine)
    with engine.begin() as connection:
        connection.execute(
            insert(t.human).values(
                id=HUMAN,
                handle="mail-race",
                display_name="Mail race",
                password_hash="not-used",
                created_at=clock.now(),
            )
        )
        grant = issue(connection)
    start = Barrier(2)

    def complete(method: str) -> bool:
        start.wait(timeout=5)
        with engine.begin() as connection:
            links.lock_human(connection, HUMAN)
            row = links.live(connection, nonce_hash=links.digest(grant.nonce))
            if row is None:
                return False
            if method == "link":
                return links.use(connection, row)
            return links.try_code(connection, row, grant.code or "", KEY)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(complete, ["link", "code"]))
    assert sum(results) == 1
