"""Single-use and guess budgets before wiring mail delivery and HTTP routes."""

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import Connection, Engine, insert, select, update

from maity_hub import clock, db
from maity_hub import tables as t
from maity_hub.auth import email_links as links
from maity_hub.auth import totp
from maity_hub.net import limit_key

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
    issued = links.issue(
        conn,
        human_id=HUMAN,
        address_epoch=1,
        pending=pending,
        source=source,
        next_path="/",
        signing_key=KEY,
    )

    assert issued is not None
    return issued


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
    # One reading for every six-digit code: the mail link's, the mail factor's and TOTP's.
    assert totp.normalise_six(value) is None
    assert totp.normalise_six("012 345") == "012345"


def test_a_new_six_digit_code_keeps_its_leading_zeros() -> None:
    drawn = {totp.new_six() for _ in range(200)}
    assert all(len(c) == 6 and c.isdigit() for c in drawn)


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
    assert ("012345" in body) == (code is not None)
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


def test_request_limits_are_address_and_source_pairs() -> None:
    limits = links.RequestLimits()
    for _ in range(3):
        assert limits.take("  HUMAN@EXAMPLE.ORG  ", "192.0.2.1") == (0, True)
    assert limits.take("human@example.org", "192.0.2.1") == (0, False)
    assert limits.take("human@example.org", "192.0.2.2") == (0, True)
    assert limits.take("unknown@example.org", "192.0.2.1") == (0, True)


def test_only_source_request_limit_is_observable() -> None:
    limits = links.RequestLimits()
    for n in range(10):
        assert limits.take(f"unknown-{n}@example.org", "192.0.2.1") == (0, True)
    wait, send = limits.take("another@example.org", "192.0.2.1")
    assert wait > 0 and not send
    assert limits.take("another@example.org", "192.0.2.2") == (0, True)


def test_an_address_gets_few_mails_however_many_sources_ask() -> None:
    limits = links.RequestLimits()
    sent = [
        limits.take("Human@Example.org", f"192.0.2.{n}")[1]
        for n in range(1, 1 + 3 * links.RECIPIENT_PER_HOUR)
    ]
    # Every request is answered alike (no wait); only the first few are delivered.
    assert sent == [True] * links.RECIPIENT_PER_HOUR + [False] * (2 * links.RECIPIENT_PER_HOUR)
    assert limits.take("other@example.org", "192.0.2.1") == (0, True)


def test_one_network_takes_one_place_of_the_address_however_often_it_asks() -> None:
    limits = links.RequestLimits()
    sent = [limits.take("human@example.org", "192.0.2.1")[1] for _ in range(10)]
    assert sent == [True] * 3 + [False] * 7  # its pair limit, three a quarter of an hour
    delivered = [limits.take("human@example.org", f"198.51.100.{n}")[1] for n in range(1, 6)]
    assert delivered == [True] * 4 + [False]  # 1 + 4 = the hour's five networks


def test_two_networks_asking_all_hour_never_stop_the_owners_mail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A1014 P1: two sources in different /64s ask for the address's link at every quarter of
    # an hour, as far as their limits let them, for thirty hours; the owner, from a third /64,
    # asks every three hours and gets a link each time.
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limits = links.RequestLimits()
    attackers = [limit_key("2001:db8:a::1"), limit_key("2001:db8:b::1")]
    owner = limit_key("2001:db8:c::1")
    delivered = []
    for quarter in range(4 * 30):
        now[0] = quarter * 900.0
        for source in attackers:
            for _ in range(3):
                delivered.append(limits.take("human@example.org", source)[1])
        if quarter % 12 == 0:
            now[0] += 2.0
            assert limits.take("human@example.org", owner) == (0, True), quarter
    assert sum(delivered) == 2 * 20  # each attacker its pair limit, 10 a day, nothing more


def test_addresses_of_one_slash_64_are_one_network_of_the_address() -> None:
    limits = links.RequestLimits()
    for n in range(1, 4):
        assert limits.take("human@example.org", limit_key(f"2001:db8:a::{n}")) == (0, True)
    others = [limits.take("human@example.org", f"198.51.100.{n}")[1] for n in range(1, 6)]
    assert others == [True] * 4 + [False]


def test_a_network_the_address_refused_does_not_hold_a_place_after() -> None:
    limits = links.RequestLimits()
    for n in range(1, 6):
        assert limits.take("human@example.org", f"198.51.100.{n}") == (0, True)
    assert limits.take("human@example.org", "203.0.113.9") == (0, False)
    # Refused, it was not marked as holding a place: asked again, it is refused again.
    assert limits.take("human@example.org", "203.0.113.9") == (0, False)
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)  # holds one


def test_the_address_limit_has_a_day_as_well(monkeypatch: pytest.MonkeyPatch) -> None:
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limits = links.RequestLimits()
    delivered = 0
    for hour in range(6):
        now[0] = hour * 3601.0
        for n in range(10):
            delivered += limits.take("human@example.org", f"203.0.113.{hour * 10 + n}")[1]
    assert delivered == links.RECIPIENT_PER_DAY


def test_instance_void_ends_every_open_link_and_code(conn: Connection) -> None:
    first = issue(conn)
    second = issue(conn, "second-browser", "192.0.2.2")
    links.void_open(conn)
    assert links.live(conn, nonce_hash=links.digest(first.nonce)) is None
    assert links.live(conn, nonce_hash=links.digest(second.nonce)) is None


@pytest.fixture
def counts(migrated: Engine) -> Iterator[None]:
    """The limits' counts as the hub keeps them: in the database on PostgreSQL, across
    replicas, else in the process."""
    from maity_hub import shared_counts

    if migrated.dialect.name == "postgresql":
        shared_counts.configure(migrated)
    yield
    shared_counts.configure(None)


def test_concurrent_requests_of_new_networks_get_no_mail_once_the_address_is_full(
    counts: None,
) -> None:
    # A1019 P7: the address's five places are taken; thirty further networks then ask three
    # times each, all at once. A request that saw another's mark set before that one was
    # refused got its mail without a place.
    limits = links.RequestLimits()
    for n in range(1, 6):
        assert limits.take("human@example.org", f"198.51.100.{n}") == (0, True)
    asks = [f"203.0.113.{n}" for n in range(1, 31) for _ in range(3)]
    with ThreadPoolExecutor(max_workers=12) as pool:
        sent = list(pool.map(lambda source: limits.take("human@example.org", source)[1], asks))
    assert sum(sent) == 0
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)  # holds its place


def test_a_network_the_day_refused_holds_no_place_of_the_hour(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    limits = links.RequestLimits()
    for hour in range(4):  # the day's twenty places, five an hour
        now[0] = hour * 3600.0
        for n in range(5):
            assert limits.take("human@example.org", f"198.51.{hour}.{n + 1}") == (0, True)
    now[0] = 86400.0 - 60  # the hour's places are free, the day's are not
    for n in range(1, 6):
        assert limits.take("human@example.org", f"203.0.113.{n}") == (0, False)
    now[0] = 86400.0 + 1  # the first hour's five day places have left the day
    # Refused by the day, those five took nothing of this hour: five new networks fit.
    sent = [limits.take("human@example.org", f"192.0.2.{n}")[1] for n in range(1, 6)]
    assert sent == [True] * 5


def _windows(times: list[float], width: float) -> int:
    """The most of `times` (sorted) inside any window of `width` seconds."""
    most, start = 0, 0
    for end, at in enumerate(times):
        while times[start] <= at - width:
            start += 1
        most = max(most, end - start + 1)
    return most


def _flood(
    limits: links.RequestLimits, now: list[float], networks: list[str] | None = None
) -> list[float]:
    """For two days, at every quarter of an hour, every network that got a mail through asks
    three times, as often as its pair limits let a mail through. With `networks` None, fresh
    networks then ask until one is refused, so that each place is taken again as soon as it
    is free: once in even hours, keeping the rest of their day's ten for late in their hold,
    three times in odd ones, early in theirs (A1019 P9). A refused network is dropped, as a
    refused ask counts against its day too. The moments of the mails sent."""
    sent: list[float] = []
    members = list(networks or [])
    fresh = (f"10.{n // 65536}.{n // 256 % 256}.{n % 256}" for n in range(1, 10**6))

    def ask(source: str) -> bool:
        if limits.take("human@example.org", source)[1]:
            sent.append(now[0])
            return True
        return False

    for step in range(2 * 24 * 4):
        now[0] = step * 900.0
        for source in members:
            for _ in range(3):
                ask(source)
        while networks is None:
            source = next(fresh)
            if not ask(source):
                break
            members.append(source)
            for _ in range(2 if step // 4 % 2 else 0):
                ask(source)
    return sent


def _clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [0.0]

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return now[0]

    monkeypatch.setattr("maity_hub.ratelimit.time", Clock)
    return now


def test_an_address_gets_at_most_50_mails_in_any_hour(monkeypatch: pytest.MonkeyPatch) -> None:
    # A1019 P9: the windows slide, so the places pass from one network to the next within an
    # hour; without a count of the mails this flood sends 60 in one.
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    limits.by_source.configure(10**6, 3600)  # one test, many networks: the source limit aside
    sent = _flood(limits, now)
    assert _windows(sent, 3600) == links.RECIPIENT_MAILS_PER_HOUR


def test_an_address_gets_at_most_200_mails_in_any_day(monkeypatch: pytest.MonkeyPatch) -> None:
    # A1019 P8: twenty networks take the day's places with one mail each and send their other
    # nine late in their hold; twenty more take the places as they come free and send their
    # ten at once. Without a count of the mails, 380 in one day.
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    sent: list[float] = []

    def ask(source: str, times: int) -> None:
        for _ in range(times):
            if limits.take("human@example.org", source)[1]:
                sent.append(now[0])

    early = [[f"198.51.{g}.{n}" for n in range(1, 6)] for g in range(4)]
    late = [[f"203.0.{g}.{n}" for n in range(1, 6)] for g in range(4)]
    for g in range(4):
        now[0] = g * 3600.0
        for source in early[g]:
            ask(source, 1)
    for g in range(4):
        for quarter in range(3):
            now[0] = (20 + g) * 3600.0 + quarter * 900
            for source in early[g]:
                ask(source, 3)
    for g in range(4):
        for quarter in range(4):
            now[0] = (24 + g) * 3600.0 + quarter * 900
            for source in late[g]:
                ask(source, 3)
    assert _windows(sent, 86400) == links.RECIPIENT_MAILS_PER_DAY
    assert _windows(sent, 3600) <= links.RECIPIENT_MAILS_PER_HOUR


def test_four_networks_at_their_pair_limits_never_reach_the_mail_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    refused: list[str] = []
    for counter in (limits.recipient_mails_hour, limits.recipient_mails_day):
        place = counter.place

        def spy(key: str, count: int = 1, place: Any = place, name: str = counter.name) -> Any:
            wait, mark = place(key, count)
            if wait:
                refused.append(name)
            return wait, mark

        monkeypatch.setattr(counter, "place", spy)
    sent = _flood(limits, now, [f"198.51.100.{n}" for n in range(1, 5)])
    assert refused == [] and len(sent) == 4 * 20  # each its 10 a day, over two days
    assert _windows(sent, 3600) <= 40 and _windows(sent, 86400) <= 40


def test_a_network_asking_again_late_in_its_hold_takes_no_second_place(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A1027 P12: a network's mark ends with its place, not before it, so asking again late in
    # the hold takes no second place: three networks leave the owner's fourth its mail.
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    for source in ("198.51.100.1", "198.51.100.2", "198.51.100.3"):
        assert limits.take("human@example.org", source) == (0, True)
    now[0] = 3591.0
    for source in ("198.51.100.1", "198.51.100.2"):
        assert limits.take("human@example.org", source) == (0, True)
    now[0] = 3595.0
    assert limits.take("human@example.org", "203.0.113.1") == (0, True)


def _places_held(limits: links.RequestLimits, now: float) -> int:
    hits = limits.recipient_hour._hits.get(links.digest("recipient\0human@example.org"), ())
    return sum(1 for at in hits if at > now - 3600)


def test_four_networks_asking_as_their_places_end_never_hold_all_five(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A1027's sustained run: four networks, ten seconds apart, ask again 9 seconds before each
    # place ends and the moment it ends, within their pair limits, for thirty hours. Not one
    # second has all five places held, so a fifth network always finds one.
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    networks = [f"198.51.100.{n}" for n in range(1, 5)]
    asks = sorted(
        (n * 10.0 + k * 3600.0 + early, source)
        for n, source in enumerate(networks)
        for k in range(30)
        for early in ((0.0,) if k == 0 else (-9.0, 0.0))
    )
    most, at = 0, 0
    for second in range(30 * 3600):
        now[0] = float(second)
        while at < len(asks) and asks[at][0] <= second:
            limits.take("human@example.org", asks[at][1])
            at += 1
        most = max(most, _places_held(limits, now[0]))
    assert most == 4


def test_a_mark_taken_late_ends_with_its_place(monkeypatch: pytest.MonkeyPatch) -> None:
    # A1027 N2: a request held 15 seconds between its place and its mark. The mark takes the
    # place's moment, so once the place has left the hour the network holds nothing there.
    now = _clock(monkeypatch)
    limits = links.RequestLimits()
    marks = limits.recipient_hour_networks
    for name in ("place", "hit"):
        original = getattr(marks, name)

        def stalled(*args: Any, original: Any = original, **kwargs: Any) -> Any:
            now[0] += 15.0
            return original(*args, **kwargs)

        monkeypatch.setattr(marks, name, stalled)
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)
    monkeypatch.undo()
    now = _clock(monkeypatch)
    now[0] = 3601.0
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)  # a new place
    others = [limits.take("human@example.org", f"203.0.113.{n}")[1] for n in range(1, 6)]
    assert others == [True] * 4 + [False]  # it holds one of the five, not none


def test_of_two_requests_of_one_network_at_once_one_gives_its_place_back(
    counts: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A1027 F5: the first request is held between its places and its mark; a second of the
    # same network runs through and marks it. The first then gives its places back, and the
    # network holds one place: four more networks fit, a fifth does not.
    limits = links.RequestLimits()
    marks = limits.recipient_hour_networks
    original = marks.place
    second: list[tuple[int, bool]] = []
    holding = [True]

    def held(key: str, count: int = 1, **kwargs: Any) -> Any:
        if holding[0]:
            holding[0] = False  # only the first request is held, once
            second.append(limits.take("human@example.org", "198.51.100.1"))
        return original(key, count, **kwargs)

    monkeypatch.setattr(marks, "place", held)
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)
    assert second == [(0, True)]
    monkeypatch.undo()
    others = [limits.take("human@example.org", f"203.0.113.{n}")[1] for n in range(1, 6)]
    assert others == [True] * 4 + [False]
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)  # it holds its one


def test_a_mark_stalled_after_its_place_lies_at_the_place_s_moment_in_the_database(
    counts: None, migrated: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A1031 N1: on PostgreSQL the mark is written at its place's own moment, not at the moment
    # it was set: a request held two seconds between the two leaves rows of equal moments.
    from maity_hub import shared_counts

    if migrated.dialect.name != "postgresql":
        pytest.skip("the rows exist on PostgreSQL only")
    real, late = shared_counts._now, [timedelta(0)]
    monkeypatch.setattr(shared_counts, "_now", lambda: real() + late[0])
    limits = links.RequestLimits()
    for marks in (limits.recipient_hour_networks, limits.recipient_day_networks):
        original = marks.place

        def stalled(*args: Any, original: Any = original, **kwargs: Any) -> Any:
            late[0] = timedelta(seconds=2)
            return original(*args, **kwargs)

        monkeypatch.setattr(marks, "place", stalled)
    assert limits.take("human@example.org", "198.51.100.1") == (0, True)

    def moments(limiter: Any) -> list[Any]:
        with migrated.connect() as conn:
            rows = conn.execute(
                select(t.rate_count.c.window_start).where(t.rate_count.c.bucket == limiter.name)
            )
            return [row.window_start for row in rows]

    assert moments(limits.recipient_hour_networks) == moments(limits.recipient_hour)
    assert moments(limits.recipient_day_networks) == moments(limits.recipient_day)
    assert len(moments(limits.recipient_hour)) == 1
