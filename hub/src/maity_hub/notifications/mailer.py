"""Notification mail (docs/api.md §18.4, §18.5): which items a human gets by mail, when,
and what the mail says. The kinds are `inbox`, `chat` and `mention`; `security` is a mail
of its own for a new sign-in.

Per kind the human chose `immediate` (within about two minutes, every item that fell due
in that window in one mail, at most ten such mails an hour), `hourly` (at the full hour),
`daily` (at `daily_at` in their time zone) or `off`. Nothing but security mail is sent in
the human's quiet hours; what fell due goes out when they end. Every item is checked
against what the human may read when the mail is built, not when it happened, and an
item goes out once. A new sign-in is a security mail of its own, immediate or off.

A mail carries only the hub's own links. Every text the hub did not write is quoted as
plain text, an agent's marked as such, and anything a mail client could turn into a
link is defanged.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from maity_hub import clock
from maity_hub import tables as t
from maity_hub.mail import outbox
from maity_hub.mail import settings as mail_settings
from maity_hub.mail.environment import MailEnvironment
from maity_hub.notifications import items, listing, preferences
from maity_hub.notifications.items import Item

log = logging.getLogger(__name__)

INTERVAL = 60.0  # seconds between passes
WINDOW = timedelta(minutes=2)  # the immediate batching window (§18.5)
IMMEDIATE_PER_HOUR = 10
DIGEST_MAX = 50
SUBJECT_MAX = 120
CONTENT_MAX = 500
MAILED_KINDS = ("inbox", "chat", "mention")
# An open matter the dashboard shows and no mail carries (§18.5).
NEVER_MAILED = ("registration_pending", "mail_disabled")

_WORDS = {
    "en": {
        "updates": "{n} updates",
        "more": "and {n} more: {url}",
        "stop": "Stop these mails ({kind}): {url}",
        "settings": "Settings: {url}",
        "wrote": "wrote",
        "only": (
            "Maity only links to {url}; a link anywhere else in this mail was not sent by Maity."
        ),
        "sign_in": "New sign-in to your Maity account",
        "sign_in_body": (
            "A new session signed in to your account at {url}.\n\n"
            "Time: {time}\nMethod: {method}\nBrowser: {browser}\nSystem: {os}\n"
            "Address: {ip}\n\nIf this was not you, end it here: {sessions}\n"
        ),
    },
    "de": {
        "updates": "{n} Neuigkeiten",
        "more": "und {n} weitere: {url}",
        "stop": "Diese Mails abbestellen ({kind}): {url}",
        "settings": "Einstellungen: {url}",
        "wrote": "schrieb",
        "only": (
            "Maity verlinkt nur auf {url}; ein Link anderswo in dieser Mail kommt nicht "
            "von Maity."
        ),
        "sign_in": "Neue Anmeldung bei deinem Maity-Konto",
        "sign_in_body": (
            "Eine neue Sitzung hat sich bei deinem Konto auf {url} angemeldet.\n\n"
            "Zeit: {time}\nMethode: {method}\nBrowser: {browser}\nSystem: {os}\n"
            "Adresse: {ip}\n\nWarst du das nicht? Hier beenden: {sessions}\n"
        ),
    },
}

_SCHEME = re.compile(r"\b([A-Za-z][A-Za-z0-9+.-]*):(?=//)")
_DOT = re.compile(r"(?<=[A-Za-z0-9-])\.(?=[A-Za-z])")


def defang(text: str) -> str:
    """No mail client turns this into a link: `https[:]//`, `example[.]org`,
    `www[.]x`, `me@example[.]org` (§18.5)."""
    return _DOT.sub("[.]", _SCHEME.sub(r"\1[:]", text))


def quoted(text: str) -> str:
    """Text the hub did not write, as plain quoted text on one line."""
    return '"' + defang(" ".join(text.split())) + '"'


def key(item: Item) -> str:
    return f"e:{item.seq}" if item.seq is not None else f"r:{item.record}"


# --- the pass ------------------------------------------------------------------------


def run(engine: Engine, env: MailEnvironment, secret_key: bytes | None, public_url: str) -> int:
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
    queued = 0
    for human_id in humans:
        try:
            with engine.begin() as conn:
                queued += for_human(conn, human_id, env.signing_key, public_url, budget)
        except Exception:  # one human's failure must not stop the others
            log.exception("notification mail for %s failed", human_id)
    return queued


def for_human(
    conn: Connection, human_id: str, signing_key: bytes, public_url: str, budget: int = 500
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
    prefs = preferences.preferences(conn, human_id)["email"]
    # What the bell's long-poll compares before it derives again, and the human's settings
    # with it: unchanged since the last pass, and nothing left waiting for its hour, means
    # there is nothing to mail, and the pass costs a few aggregates, not 30 days of the
    # human's projects (§18.2). A settings change (a mode turned on, a new address) is a
    # change too; the old items it frees would otherwise wait for a new event.
    moved = json.dumps([listing.stamp(conn, human_id), prefs, row.verified_at], default=str)
    if state.stamp == moved and not state.waiting and state.held_since is None:
        return 0
    zone = ZoneInfo(prefs["timezone"])
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
        for i in items.derive(conn, where)
        if not i.read
        and not i.redacted  # a redacted event reaches no mail at all (§18.5)
        and i.record_type not in NEVER_MAILED
        and key(i) not in sent
        and (since is None or i.at >= since)
    ]
    modes = {kind: (prefs["kinds"].get(kind) or {}).get("mode", "off") for kind in prefs["kinds"]}
    queued = 0
    # A new sign-in is a security mail of its own; quiet hours do not hold it (§2.6.5).
    for item in pending:
        if item.record_type == "session_created" and modes.get("security") == "immediate":
            _sign_in_mail(conn, row, item, prefs, signing_key, public_url, local)
            _mark(conn, human_id, [item])
            queued += 1
    mailable = [i for i in pending if i.kind in MAILED_KINDS]
    if _quiet(prefs.get("quiet_hours"), local):
        _set_state(conn, human_id, stamp=moved, waiting=_waiting(mailable, modes))
        return queued
    # What falls due in this pass goes out as one mail, so a pass sends at most one per
    # human and the instance's budget is checked right before that one send.
    due: list[Item] = []
    clocks: dict[str, datetime | None] = {}
    if state.held_since is not None:
        due = [i for i in mailable if modes.get(i.kind) in ("immediate", "hourly", "daily")]
        clocks = {"hourly_at": now, "daily_at": now}
    else:
        immediate = [i for i in mailable if modes.get(i.kind) == "immediate"]
        capped = _immediate_this_hour(conn, human_id, now) >= IMMEDIATE_PER_HOUR
        if immediate and not capped and min(i.at for i in immediate) <= now - WINDOW:
            due += immediate
            immediate = []
        hour = now.replace(minute=0, second=0, microsecond=0)
        if state.hourly_at is None:
            clocks["hourly_at"] = hour
        elif state.hourly_at < hour:
            # The capped immediate items of the hour go with the hour's digest (§18.5).
            due += [i for i in mailable if modes.get(i.kind) == "hourly"] + immediate
            clocks["hourly_at"] = now
        today = datetime.combine(local.date(), time.fromisoformat(prefs["daily_at"]), tzinfo=zone)
        if state.daily_at is None:
            clocks["daily_at"] = now
        elif local >= today and state.daily_at < today:
            due += [i for i in mailable if modes.get(i.kind) == "daily"]
            clocks["daily_at"] = now
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


def _waiting(mailable: list[Item], modes: dict[str, str]) -> bool:
    """Whether an item is left that a mode will mail some time: an `off` kind never is,
    so it does not keep the human's passes deriving."""
    return any(modes.get(i.kind, "off") != "off" for i in mailable)


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
    words = _WORDS[prefs["language"]]
    subject, body, kinds = compose(conn, chosen, prefs, public_url, zone)
    tokens = {
        kind: preferences.unsubscribe_token(signing_key, row.human_id, kind, row.epoch)
        for kind in kinds
    }
    links = {kind: f"{public_url}/mail/unsubscribe/{token}" for kind, token in tokens.items()}
    body += "\n" + "\n".join(words["stop"].format(kind=k, url=links[k]) for k in kinds)
    body += "\n" + words["settings"].format(url=f"{public_url}/#/account/notifications")
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
    words = _WORDS[prefs["language"]]
    projects = _project_names(conn, chosen)
    if len(chosen) == 1:
        only = chosen[0]
        name = projects.get(only.project_id or "", "Maity")
        subject = f"[Maity] {name}: {only.title or ''}"
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
        lines.append(words["more"].format(n=len(chosen) - DIGEST_MAX, url=f"{public_url}/#/"))
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
    words = _WORDS[prefs["language"]]
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
        sessions=f"{public_url}/#/account/sessions",
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
                run(self.engine, self.env, self.secret_key, self.public_url)
            except Exception:
                log.exception("notification mail: a pass failed")
