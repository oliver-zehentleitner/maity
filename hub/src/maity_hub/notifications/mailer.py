"""Notification mail (docs/api.md §18.4, §18.5): which items a human gets by mail, when,
and what the mail says. The kinds are `inbox`, `chat`, `mention` and `invitation`; `security`
is a mail of its own for a new sign-in.

Per kind the human chose `immediate` (within about two minutes, every item that fell due
in that window in one mail, at most ten such mails an hour), `hourly` (at the full hour),
`daily` (at `daily_at` in their time zone), `weekly` (at `daily_at` on `weekly_on`) or
`off`. Nothing but immediate security mail is sent in the human's quiet hours; what fell
due goes out when they end. Every item is checked against what the human may read when
the mail is built, not when it happened, and an item goes out once. A new sign-in is a
security mail of its own when `security` is immediate, and an item of a digest when the
human put security in one (context/notifications.md da12f2b5).

A mail carries only the hub's own links. Every text the hub did not write is quoted as
plain text, an agent's marked as such, and anything a mail client could turn into a
link is defanged.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import UTC, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import catalog, clock, worker_runs
from maity_hub import tables as t
from maity_hub.auth import second_factor
from maity_hub.mail import headers, outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.mail.environment import MailEnvironment
from maity_hub.notifications import items, listing, preferences, presence, records
from maity_hub.notifications.items import Item

log = logging.getLogger(__name__)

INTERVAL = 60.0  # seconds between passes
WINDOW = timedelta(minutes=2)  # the immediate batching window (§18.5)
IMMEDIATE_PER_HOUR = 10
DIGEST_MAX = 50
SUBJECT_MAX = 120
CONTENT_MAX = 500
MAILED_KINDS = ("inbox", "chat", "mention", "invitation")
# An open matter the dashboard shows and no mail carries (§18.5).
NEVER_MAILED = ("registration_pending", "mail_disabled")
# The alert of a new sign-in: a security mail of its own while `security` is immediate, an
# item of the digest the human put security in, none when off (§18.4, §2.6.5).
SIGN_IN_ALERT = records.SIGN_IN
# A takeover under way: a security mail of its own at once, whatever the mode, never held
# by quiet hours, with no unsubscribe link (§18.4 "At once, whatever the mode", §2.8).
AT_ONCE = ("second_factor_changed", "second_factor_failed", "password_reset", "password_changed")
PASSWORD = ("password_reset", "password_changed")


_SCHEME_CHARS = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+.-")
_WORD = re.compile(r"\w")
_DOT = re.compile(r"(?<=[A-Za-z0-9-])\.(?=[A-Za-z])")


def _schemes(text: str) -> str:
    """`scheme://` as `scheme[:]//`: a letter at a word's start, then letters, digits, `+`,
    `.` or `-` up to the `:`. Each `://` looks back over its own run only, so the work grows
    with the text's length; the pattern it replaces tried every word start of a long run."""
    out = []
    last = 0
    at = text.find("://")
    while at >= 0:
        start = at
        while start > last and text[start - 1] in _SCHEME_CHARS:
            start -= 1
        # The leftmost letter at a word boundary: the run's first character after a
        # character that is no word character, or one after a `+`, `.` or `-`.
        boundary = (start == 0 or not _WORD.match(text[start - 1])) and start < at
        found = start < at and text[start].isascii() and text[start].isalpha() and boundary
        found = found or any(
            text[i - 1] in "+.-" and text[i].isascii() and text[i].isalpha()
            for i in range(start + 1, at)
        )
        if found:
            out.append(text[last:at])
            out.append("[:]")
            last = at + 1
        at = text.find("://", at + 1)
    out.append(text[last:])
    return "".join(out)


def defang(text: str) -> str:
    """No mail client turns this into a link: `https[:]//`, `example[.]org`,
    `www[.]x`, `me@example[.]org` (§18.5)."""
    return _DOT.sub("[.]", _schemes(text))


def quoted(text: str) -> str:
    """Text the hub did not write, as plain quoted text on one line."""
    return '"' + defang(" ".join(text.split())) + '"'


def key(item: Item) -> str:
    return f"e:{item.seq}" if item.seq is not None else f"r:{item.record}"


# --- the pass ------------------------------------------------------------------------


def run(
    engine: Engine,
    env: MailEnvironment,
    secret_key: bytes | None,
    public_url: str,
    stop: worker_runs.Stopping | None = None,
) -> int:
    """One pass over every human with a verified address; returns mails queued."""
    with engine.begin() as conn:
        resolved = mail_settings.resolve(conn, env, secret_key)
        if not (resolved.complete and resolved.enabled) or env.signing_key is None:
            return 0
        humans = list(
            conn.execute(
                select(t.notification_settings.c.human_id).where(
                    t.notification_settings.c.address_status == "verified"
                )
            ).scalars()
        )
    budget = int(resolved.value("max_per_hour"))
    grace = timedelta(minutes=int(resolved.value("online_grace_minutes")))
    queued = 0
    for human_id in humans:
        if stop is not None and stop.is_set():
            break
        try:
            with engine.begin() as conn:
                queued += for_human(conn, human_id, env.signing_key, public_url, budget, grace)
        except Exception:  # one human's failure must not stop the others
            log.exception("notification mail for %s failed", human_id)
    return queued


def for_human(
    conn: Connection,
    human_id: str,
    signing_key: bytes,
    public_url: str,
    budget: int = 500,
    grace: timedelta = timedelta(minutes=5),
) -> int:
    """One human's pass. It holds the human's settings row (`FOR UPDATE`) to its end, so
    a second process passing over the same human waits, then finds what the first one
    mailed in `mail_item_sent` and the digest clocks moved: nothing goes twice."""
    row = conn.execute(
        select(t.notification_settings)
        .where(t.notification_settings.c.human_id == human_id)
        .with_for_update()
    ).one()
    if row.address_status != "verified" or row.address is None:
        return 0
    state = _state(conn, human_id)
    # The settings, with the language this mail is in (§6.2).
    email = preferences.preferences(conn, human_id)["email"]
    prefs = {**email, "language": preferences.text_language(conn, human_id)}
    # What the bell's long-poll compares before it derives again, and the human's settings
    # with it: unchanged since the last pass, and nothing left waiting for its hour, means
    # there is nothing to mail, and the pass costs a few aggregates, not 30 days of the
    # human's projects (§18.2). A settings change (a mode turned on, a new address) is a
    # change too; the old items it frees would otherwise wait for a new event.
    moved = json.dumps([listing.stamp(conn, human_id), prefs, row.verified_at], default=str)
    if state.stamp == moved and not state.waiting and state.held_since is None:
        return 0
    zone = preferences.mail_zone(prefs)
    now = clock.now()
    local = now.astimezone(zone)
    where = items.scope(conn, human_id, public_url)
    sent = set(
        conn.execute(
            select(t.mail_item_sent.c.item).where(t.mail_item_sent.c.human_id == human_id)
        ).scalars()
    )
    since = row.verified_at
    pending = [
        i
        for i in items.derive(conn, where, sign_ins=True)
        if not i.read
        and not i.redacted  # a redacted event reaches no mail at all (§18.5)
        and i.record_type not in NEVER_MAILED
        and key(i) not in sent
        and (since is None or i.at >= since)
    ]
    modes = {kind: (prefs["kinds"].get(kind) or {}).get("mode", "off") for kind in prefs["kinds"]}
    queued = 0
    # Security mails of their own; quiet hours do not hold them (§2.6.5, §18.4).
    for item in pending:
        if item.record_type in PASSWORD:
            _password_mail(conn, row, item, prefs, public_url, local)
        elif item.record_type in AT_ONCE:
            _two_factor_mail(conn, row, item, prefs, signing_key, public_url, local)
        elif item.record_type == SIGN_IN_ALERT and modes.get("security") == "immediate":
            _sign_in_mail(conn, row, item, prefs, signing_key, public_url, local)
        else:
            continue
        _mark(conn, human_id, [item])
        queued += 1
    # Security in a digest travels with it like any kind (§18.4).
    digested_security = modes.get("security") in preferences.DIGESTS
    mailable = [
        i
        for i in pending
        if i.kind in MAILED_KINDS or (digested_security and i.record_type == SIGN_IN_ALERT)
    ]
    if _quiet(prefs.get("quiet_hours"), local):
        _set_state(conn, human_id, stamp=moved, waiting=_waiting(mailable, modes))
        return queued
    # Held while present (§18.5): the immediate items wait while the human is in the web app
    # and for the grace after; the mail of a suspension (`urgent`) never does. A held item
    # stays in `mailable`, so `waiting` keeps the passes coming until the hold ends.
    present = bool(prefs.get("hold_while_online", True)) and presence.held(
        conn, human_id, now, grace
    )

    def held(item: Item) -> bool:
        return present and not item.urgent and _mode(item, modes) == "immediate"

    # What falls due in this pass goes out as one mail, so a pass sends at most one per
    # human and the instance's budget is checked right before that one send.
    due: list[Item] = []
    clocks: dict[str, datetime | None] = {}
    if state.held_since is not None:
        due = [i for i in mailable if _mode(i, modes) != "off" and not held(i)]
        clocks = {"hourly_at": now, "daily_at": now, "weekly_at": now}
    else:
        immediate = [i for i in mailable if _mode(i, modes) == "immediate" and not held(i)]
        capped = _immediate_this_hour(conn, human_id, now) >= IMMEDIATE_PER_HOUR
        hour = now.replace(minute=0, second=0, microsecond=0)
        if immediate and not capped and min(i.at for i in immediate) <= now - WINDOW:
            due += immediate
            immediate = []
        elif capped:
            # A capped item from an hour that ended while the human was present missed that
            # hour's mail: it goes with the first pass after the grace, as the hour's mail
            # would have, not at a later hour's end (§18.5, "Held while present").
            late = [i for i in immediate if i.at < hour]
            due += late
            immediate = [i for i in immediate if i.at >= hour]
        if state.hourly_at is None:
            clocks["hourly_at"] = hour
        elif state.hourly_at < hour:
            # The capped immediate items of the hour go with the hour's digest (§18.5).
            due += [i for i in mailable if _mode(i, modes) == "hourly"] + immediate
            clocks["hourly_at"] = now
        # As an instant: a wall time compares by its digits within one zone, so a `daily_at`
        # in the hour the clocks skip would fall due twice (once by its digits, once by UTC).
        today = datetime.combine(
            local.date(), time.fromisoformat(prefs["daily_at"]), tzinfo=zone
        ).astimezone(UTC)
        if state.daily_at is None:
            clocks["daily_at"] = now
        elif now >= today and state.daily_at < today:
            due += [i for i in mailable if _mode(i, modes) == "daily"]
            clocks["daily_at"] = now
        week = _last_weekly(local, prefs["daily_at"], prefs["weekly_on"], zone)
        if state.weekly_at is None:
            clocks["weekly_at"] = now
        elif state.weekly_at < week:
            due += [i for i in mailable if _mode(i, modes) == "weekly"]
            clocks["weekly_at"] = now
    if due:
        if _instance_full(conn, budget):
            # Over the instance's budget nothing waits in a queue of its own: the
            # items stay pending and go out merged into the human's next mail (§18.5).
            _set_state(
                conn,
                human_id,
                held_since=state.held_since or now,
                stamp=moved,
                waiting=True,
                **clocks,
            )
            return queued
        unique = list({key(i): i for i in due}.values())
        queued += _send(conn, row, unique, prefs, signing_key, public_url, zone)
        clocks["held_since"] = None
        mailed = {key(i) for i in unique}
        mailable = [i for i in mailable if key(i) not in mailed]
    # What is left waits for its hour or day: the next pass must derive again.
    _set_state(conn, human_id, stamp=moved, waiting=_waiting(mailable, modes), **clocks)
    return queued


def _last_weekly(local: datetime, daily_at: str, weekly_on: str, zone: tzinfo) -> datetime:
    """The latest `weekly_on` at `daily_at` not after `local`, as an instant in UTC: a pass
    that missed the moment (the hub was down) still sends the week's digest at its next pass.
    Compared as a wall time, a `daily_at` the clocks skip fell due twice."""
    back = (local.weekday() - preferences.WEEKDAYS.index(weekly_on)) % 7
    day = local.date() - timedelta(days=back)
    at = datetime.combine(day, time.fromisoformat(daily_at), tzinfo=zone).astimezone(UTC)
    if at <= local:
        return at
    return datetime.combine(
        day - timedelta(days=7), time.fromisoformat(daily_at), tzinfo=zone
    ).astimezone(UTC)


def _mode(item: Item, modes: dict[str, str]) -> str:
    """The item's kind's mode; an `urgent` item goes at once whatever it says (§18.5): a
    suspended account's notice, which it can read nowhere else (§16.8)."""
    return "immediate" if item.urgent else modes.get(item.kind, "off")


def _waiting(mailable: list[Item], modes: dict[str, str]) -> bool:
    """Whether an item is left that a mode will mail some time: an `off` kind never is,
    so it does not keep the human's passes deriving."""
    return any(_mode(i, modes) != "off" for i in mailable)


def _quiet(hours: Any, local: datetime) -> bool:
    """Inside `quiet_hours`, which may cross midnight."""
    if not hours:
        return False
    start, end, now = (
        time.fromisoformat(hours["from"]),
        time.fromisoformat(hours["to"]),
        local.time(),
    )
    return start <= now < end if start <= end else now >= start or now < end


def _instance_full(conn: Connection, budget: int) -> bool:
    """The notification mail of the last hour, sent or waiting, has reached the
    instance's `max_per_hour` (§16.2)."""
    sent = conn.execute(
        select(func.count()).where(
            t.mail_delivery.c.kind == "notification",
            t.mail_delivery.c.outcome == "sent",
            t.mail_delivery.c.at >= clock.now() - timedelta(hours=1),
        )
    ).scalar_one()
    waiting = conn.execute(
        select(func.count()).where(
            t.mail_outbox.c.kind == "notification",
            t.mail_outbox.c.status.in_(("waiting", "sending")),
        )
    ).scalar_one()
    return int(sent) + int(waiting) >= budget


def _immediate_this_hour(conn: Connection, human_id: str, now: datetime) -> int:
    return int(
        conn.execute(
            select(func.count()).where(
                t.mail_outbox.c.human_id == human_id,
                t.mail_outbox.c.kind == "notification",
                t.mail_outbox.c.created_at >= now - timedelta(hours=1),
            )
        ).scalar_one()
    )


def _state(conn: Connection, human_id: str) -> Any:
    found = conn.execute(
        select(t.notification_mail_state).where(t.notification_mail_state.c.human_id == human_id)
    ).first()
    if found is None:
        try:
            with conn.begin_nested():  # another process may make it at the same moment
                conn.execute(insert(t.notification_mail_state).values(human_id=human_id))
        except IntegrityError:
            pass
        found = conn.execute(
            select(t.notification_mail_state).where(
                t.notification_mail_state.c.human_id == human_id
            )
        ).one()
    return found


def _set_state(conn: Connection, human_id: str, **values: Any) -> None:
    conn.execute(
        update(t.notification_mail_state)
        .where(t.notification_mail_state.c.human_id == human_id)
        .values(**values)
    )


def _mark(conn: Connection, human_id: str, chosen: list[Item]) -> None:
    now = clock.now()
    for item in chosen:
        conn.execute(
            insert(t.mail_item_sent).values(human_id=human_id, item=key(item), mailed_at=now)
        )


# --- the mails -----------------------------------------------------------------------


def _send(
    conn: Connection,
    row: Any,
    chosen: list[Item],
    prefs: dict[str, Any],
    signing_key: bytes,
    public_url: str,
    zone: ZoneInfo,
) -> int:
    chosen = sorted(chosen, key=lambda i: i.order)
    words = catalog.section("mail", prefs["language"])
    subject, body, kinds = compose(conn, chosen, prefs, public_url, zone)
    tokens = {
        kind: preferences.unsubscribe_token(signing_key, row.human_id, kind, row.epoch)
        for kind in kinds
    }
    links = {kind: f"{public_url}/mail/unsubscribe/{token}" for kind, token in tokens.items()}
    body += "\n" + "\n".join(words["stop"].format(kind=k, url=links[k]) for k in kinds)
    body += "\n" + words["settings"].format(url=f"{public_url}/account/notifications")
    body += "\n\n" + words["only"].format(url=public_url) + "\n"
    outbox.enqueue(
        conn,
        kind="notification",
        human_id=row.human_id,
        to=row.address,
        subject=subject,
        body=body,
        extra_headers={
            "List-Unsubscribe": f"<{links[kinds[0]]}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )
    _mark(conn, row.human_id, chosen)
    return 1


def compose(
    conn: Connection, chosen: list[Item], prefs: dict[str, Any], public_url: str, zone: ZoneInfo
) -> tuple[str, str, list[str]]:
    """(subject, body without the closing lines, the kinds in the mail, in order)."""
    words = catalog.section("mail", prefs["language"])
    projects = _project_names(conn, chosen)
    if len(chosen) == 1:
        only = chosen[0]
        name = projects.get(only.project_id or "", "Maity")
        # A project's name and a title are text the hub did not write: one line (§18.5).
        subject = headers.clean(f"[Maity] {name}: {only.title or ''}")
    else:
        subject = "[Maity] " + words["updates"].format(n=len(chosen))
    if len(subject) > SUBJECT_MAX:
        subject = subject[: SUBJECT_MAX - 1] + "…"
    lines: list[str] = []
    shown = chosen[:DIGEST_MAX]
    for project_id in dict.fromkeys(i.project_id for i in shown):
        lines.append(quoted(projects.get(project_id or "", "Maity")))
        for item in (i for i in shown if i.project_id == project_id):
            stamp = item.at.astimezone(zone).strftime("%Y-%m-%d %H:%M")
            lines.append(f"- {quoted(item.title or '')}")
            lines.append(f"  {stamp} {item.url}")
            content = (prefs["kinds"].get(item.kind) or {}).get("content")
            text = _message_text(conn, item) if content else None
            if text:
                # A display name is text the hub did not write either (§18.5).
                writer = defang(" ".join(items.actor_name(conn, item.actor_membership).split()))
                lines.append(f"  {writer} {words['wrote']}: {quoted(text[:CONTENT_MAX])}")
        lines.append("")
    if len(chosen) > DIGEST_MAX:
        lines.append(words["more"].format(n=len(chosen) - DIGEST_MAX, url=f"{public_url}/"))
    kinds = list(dict.fromkeys(i.kind for i in chosen))
    return subject, "\n".join(lines), kinds


def _message_text(conn: Connection, item: Item) -> str | None:
    """A `chat` or `mention` message's text, only for an event that was not redacted:
    the item is the notification, the text stays in the event (§18.5)."""
    if item.seq is None or item.redacted or item.kind not in ("chat", "mention"):
        return None
    row = conn.execute(
        select(t.event.c.payload, t.event.c.redacted).where(t.event.c.seq == item.seq)
    ).first()
    if row is None or row.redacted:
        return None
    body = (row.payload or {}).get("body")
    return body if isinstance(body, str) and body.strip() else None


def _project_names(conn: Connection, chosen: list[Item]) -> dict[str, str]:
    ids = {i.project_id for i in chosen if i.project_id}
    if not ids:
        return {}
    rows = conn.execute(select(t.project.c.id, t.project.c.name).where(t.project.c.id.in_(ids)))
    return {row.id: row.name for row in rows}


def _sign_in_mail(
    conn: Connection,
    row: Any,
    item: Item,
    prefs: dict[str, Any],
    signing_key: bytes,
    public_url: str,
    local: datetime,
) -> None:
    """Time, method, browser, system and address of the new session, and where to end
    it; never a session id, a code or a link that signs anyone in (§2.6.5)."""
    words = catalog.section("mail", prefs["language"])
    record = conn.execute(select(t.account_record).where(t.account_record.c.n == item.record)).one()
    data = record.data or {}
    token = preferences.unsubscribe_token(signing_key, row.human_id, "security", row.epoch)
    stop = f"{public_url}/mail/unsubscribe/{token}"
    body = words["sign_in_body"].format(
        url=public_url,
        time=record.at.astimezone(local.tzinfo).strftime("%Y-%m-%d %H:%M %Z"),
        method=data.get("method"),
        browser=data.get("browser") or "?",
        os=data.get("os") or "?",
        ip=data.get("ip") or "?",
        sessions=f"{public_url}/account/sessions",
    )
    body += "\n" + words["stop"].format(kind="security", url=stop)
    body += "\n\n" + words["only"].format(url=public_url) + "\n"
    outbox.enqueue(
        conn,
        kind="security",
        human_id=row.human_id,
        to=row.address,
        subject=f"[Maity] {words['sign_in']}",
        body=body,
        extra_headers={
            "List-Unsubscribe": f"<{stop}>",
            "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
        },
    )


def _two_factor_mail(
    conn: Connection,
    row: Any,
    item: Item,
    prefs: dict[str, Any],
    signing_key: bytes | None,
    public_url: str,
    local: datetime,
) -> None:
    """A change of the second factor, or wrong codes after a sign-in (§2.8.1): what happened
    and when, and where to look; never a code or a secret. The one link that changes anything
    is the daily cap's (§2.8.6): it lifts the cap for the rest of that day, once. No mode turns
    it off, so it carries no unsubscribe link (§18.4)."""
    words = catalog.section("mail", prefs["language"])
    record = conn.execute(select(t.account_record).where(t.account_record.c.n == item.record)).one()
    body = words["two_factor_body"].format(
        title=item.title,
        time=record.at.astimezone(local.tzinfo).strftime("%Y-%m-%d %H:%M %Z"),
        security=f"{public_url}/account/security",
    )
    data = record.data or {}
    if (
        record.type == "second_factor_failed"
        and data.get("method") == second_factor.DAILY_LIMIT
        and signing_key is not None
        and isinstance(data.get("day"), str)
        and isinstance(data.get("unlocks"), int)
        and isinstance(data.get("password_generation"), int)
    ):
        token = second_factor.unlock_token(
            signing_key, row.human_id, data["day"], data["unlocks"], data["password_generation"]
        )
        body += "\n" + words["two_factor_unlock"].format(
            link=f"{public_url}/mail/second-factor-unlock/{token}"
        )
    body += "\n" + words["settings"].format(url=f"{public_url}/account/notifications")
    body += "\n\n" + words["only"].format(url=public_url) + "\n"
    outbox.enqueue(
        conn,
        kind="security",
        human_id=row.human_id,
        to=row.address,
        subject=headers.clean(f"[Maity] {item.title}"),
        body=body,
    )


def _password_mail(
    conn: Connection,
    row: Any,
    item: Item,
    prefs: dict[str, Any],
    public_url: str,
    local: datetime,
) -> None:
    """A completed reset (§2.10) or a changed password (§2.1): when and from where, which
    sessions have ended, and what to do if it was not the human. At once whatever the mode, so
    no unsubscribe link."""
    words = catalog.section("mail", prefs["language"])
    record = conn.execute(select(t.account_record).where(t.account_record.c.n == item.record)).one()
    data = record.data or {}
    unknown = catalog.section("notify", prefs["language"])
    kind = str(record.type)  # `password_reset` or `password_changed`
    body = words[f"{kind}_body"].format(
        time=record.at.astimezone(local.tzinfo).strftime("%Y-%m-%d %H:%M %Z"),
        browser=data.get("browser") or unknown["a_browser"],
        os=data.get("os") or unknown["unknown_os"],
        ip=data.get("ip") or "?",
        agents=f"{public_url}/agents",
    )
    body += "\n" + words["settings"].format(url=f"{public_url}/account/notifications")
    body += "\n\n" + words["only"].format(url=public_url) + "\n"
    outbox.enqueue(
        conn,
        kind="security",
        human_id=row.human_id,
        to=row.address,
        subject=f"[Maity] {words[f'{kind}_subject']}",
        body=body,
    )


class Worker:
    """Builds notification mail in the background, once a minute."""

    def __init__(
        self,
        engine: Engine,
        env: MailEnvironment,
        secret_key: bytes | None,
        public_url: str,
        interval: float = INTERVAL,
    ) -> None:
        self.engine, self.env, self.secret_key = engine, env, secret_key
        self.public_url, self.interval = public_url, interval
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="maity-notify-mail", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                with worker_runs.claim(
                    self.engine, "notification-mail", self.interval, self._stop
                ) as held:
                    if held is not None:
                        run(self.engine, self.env, self.secret_key, self.public_url, held)
            except Exception:
                log.exception("notification mail: a pass failed")
