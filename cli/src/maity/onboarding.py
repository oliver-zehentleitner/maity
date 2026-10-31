"""The resume packet as text for the agent that reads it (docs/api.md §5.2).

`maity join` and `maity resume` print this; `--json` prints the packet itself. The order is
what an agent needs first: whether it is isolated or paused, the briefing a human wrote for it,
who it is, the project, the rules, its work, what it missed, and the next step.

Nearly every string in the packet was written by someone: the briefing, messages and answers,
but also card titles, checkpoints, reply labels and display names. Two rules keep that text
from passing for this command's own output:

- every string is cleaned before it is printed (`clean`): terminal escapes, other control
  characters and bidi overrides are shown as visible escapes, so nothing can move the cursor,
  erase a line or reorder what the reader sees;
- text that may span lines is printed quoted, every line behind `> ` (`quote`), and every other
  field is collapsed onto one line (`inline`), so no field can start a line of the output.

Long text is capped in this rendering only (`MAX_BODY_*`, `MAX_EVENTS_CHARS`) with a pointer to
the full value; `--json` stays complete. By default the text is compact (`COMPACT_*`): the last
answers and the last events addressed to this member or instance, the rest counted, shorter
bodies; `maity resume --full` renders the same packet without that.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from maity import pointer

HANDBOOK = "https://github.com/oliver-zehentleitner/maity/blob/main/docs/agents.md"
MAX_BODY_LINES = 40
MAX_BODY_CHARS = 4000
MAX_EVENTS_CHARS = 64 * 1024
COMPACT_ANSWERS = 10
COMPACT_EVENTS = 10
COMPACT_LINES = 5
COMPACT_CHARS = 200
COMPACT_KINDS = 5
FULL = "maity resume --full"
WAIT_ON = (
    ", then start maity wait in the background and keep working from what it returns. "
    "Do not wait for your human in the terminal."
)

# Characters a terminal acts on rather than shows, plus the Unicode line and paragraph
# separators, which some readers break lines on. Kept: newline (handled by quote/inline) and
# tab (it can only move right).
_BIDI = {0x061C, 0x200E, 0x200F, 0x2028, 0x2029, *range(0x202A, 0x202F), *range(0x2066, 0x206A)}


def _visible(ch: str) -> str:
    code = ord(ch)
    return f"\\x{code:02x}" if code < 0x100 else f"\\u{code:04x}"


def clean(text: Any) -> str:
    """`text` as a string with every control, C1 and bidi character shown as an escape."""
    out = []
    for ch in str(text):
        code = ord(ch)
        dangerous = (
            (code < 0x20 and ch not in "\n\t") or code == 0x7F or 0x80 <= code <= 0x9F
        ) or code in _BIDI
        out.append(_visible(ch) if dangerous else ch)
    return "".join(out)


def inline(text: Any) -> str:
    """A field printed inside a line: cleaned, its line breaks shown as `\\n`."""
    return clean(text).replace("\n", "\\n")


def quote(text: Any) -> list[str]:
    """Every line of `text`, cleaned, behind `> `, so nothing in it reads as a line of output."""
    lines = clean(text).rstrip("\n").split("\n")
    return [f"> {line}".rstrip() for line in lines]


def _capped(text: Any, pointer: str, compact: bool = False) -> list[str]:
    """`quote(text)`, cut at MAX_BODY_LINES lines or MAX_BODY_CHARS characters, or at the
    COMPACT_* ones in the compact text."""
    max_lines, max_chars = (
        (COMPACT_LINES, COMPACT_CHARS) if compact else (MAX_BODY_LINES, MAX_BODY_CHARS)
    )
    full = str(text)
    lines = full.rstrip("\n").split("\n")
    kept: list[str] = []
    size = 0
    for line in lines:
        if len(kept) == max_lines or size + len(line) > max_chars:
            break
        kept.append(line)
        size += len(line) + 1
    if len(kept) == len(lines):
        return quote(full)
    if not kept:  # one line longer than the cap
        kept = [lines[0][:max_chars]]
    rest = len(lines) - len(kept)
    return [*quote("\n".join(kept)), f"… (cut, {rest} more lines: {pointer})"]


def get(data: Any, *keys: str) -> Any:
    """`data[k1][k2]…`, or None where a level is missing or not a dict."""
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _dict(data: Any) -> dict[str, Any]:
    return data if isinstance(data, dict) else {}


def _items(data: Any) -> list[dict[str, Any]]:
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


_ID_SHAPED = re.compile(r"^(agt|hum|role|area)[-:]", re.IGNORECASE)


# A team's global name `owner/handle` (§6.3). The check-in target is a member, never an
# instance, so an `…#id` (an instance mention, §8.6) falls back like any other value here.
_GLOBAL_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}/[a-z0-9][a-z0-9-]{0,62}$")


def shown_names(members: Iterable[tuple[Any, Any, Any, Any]]) -> dict[str, str]:
    """member id → the name to show, from (member id, kind, handle, global name): the
    handle, unique among the members given; for agents sharing a short handle, each one's
    global name `owner/handle` (§6.3) when the hub sent it. A human keeps its handle when
    only agents share it: a human comes first and has no long form (§8.6). A name stays out
    when it could be read as something else: shared without a global name, shaped like an
    id or an address, or `all`; that member keeps its id."""
    rows = [
        (
            member_id,
            kind,
            handle,
            name if isinstance(name, str) and _GLOBAL_NAME.match(name) else None,
        )
        for member_id, kind, handle, name in members
        if isinstance(member_id, str) and isinstance(handle, str) and handle
    ]
    sharers: dict[str, list[tuple[str, Any]]] = {}
    for member_id, kind, handle, _ in rows:
        sharers.setdefault(_key(handle), []).append((member_id, kind))
    shown: dict[str, str] = {}
    for member_id, kind, handle, name in rows:
        if _ID_SHAPED.match(_key(handle)) or _key(handle) in ("all", ""):
            continue
        others = [k for m, k in sharers[_key(handle)] if m != member_id]
        if not others or (kind == "human" and all(k == "agent" for k in others)):
            shown[member_id] = handle
        elif name is not None:
            shown[member_id] = name
    return shown


def label(member: Any) -> str:
    """One member object as a reader names it outside a member list: its global name when
    the hub sent one, else its handle, else its id (§6.3)."""
    member = _dict(member)
    name = member.get("name")
    if isinstance(name, str) and _GLOBAL_NAME.match(name):
        return name
    return inline(member.get("handle") or member.get("member_id") or member.get("id") or "?")


def _names(packet: dict[str, Any]) -> dict[str, str]:
    """member id → name, from the peers and this member itself: a human reads names. The
    packet's peers carry no global name yet; for this member it is built from `me.owner`."""
    me = _dict(packet.get("me"))
    owner, handle = get(me, "owner", "handle"), me.get("handle")
    mine = me.get("name")
    if not mine and isinstance(owner, str) and isinstance(handle, str):
        mine = f"{owner}/{handle}"
    members = [
        *((m.get("member_id"), m.get("kind"), m.get("handle"), m.get("name"))
          for m in _items(packet.get("peers"))),
        (me.get("member_id"), "agent", handle, mine),
    ]  # fmt: skip
    return shown_names(members)


def _key(handle: str) -> str:
    """What a reader takes the handle for: format characters (zero-width, direction marks)
    and surrounding space dropped, case folded."""
    return "".join(c for c in handle if unicodedata.category(c) != "Cf").strip().casefold()


def _name(value: Any, names: dict[str, str]) -> str:
    """A member's handle when the packet names it, else the value as it is (an id)."""
    return inline(names.get(value, value) if isinstance(value, str) else value)


DORMANT_OFF = "maity dormant --off"


def _who(packet: dict[str, Any], names: dict[str, str]) -> list[str]:
    me, ms = _dict(packet.get("me")), _dict(packet.get("membership"))
    member_id = me.get("member_id")
    shown = names.get(member_id) if isinstance(member_id, str) else None
    handle = inline(shown or me.get("handle") or me.get("member_id") or "?")
    name = me.get("display_name")
    instance = me.get("instance")  # §6.17
    line = f"You are {handle}" + (f"#{inline(instance)}" if instance else "")
    line += f" ({inline(name)})" if name and inline(name) != handle else ""
    if me.get("member_id"):
        line += f", member id {inline(me['member_id'])}"
    lines = [line + "."]
    others = [_sibling(handle, i) for i in _items(packet.get("team"))]
    if others:
        lines.append("Other instances of you: " + "; ".join(others))
    if me.get("dormant") and instance:  # §6.17
        address = f"@{handle}#{inline(instance)}"
        lines.append(f"Dormant: only {address} wakes this instance. End it with: {DORMANT_OFF}")
    if ms.get("trust") or ms.get("role"):
        role = _trust_role(ms, "Trust: {trust}, role: {role}")
        if ms.get("reports_to"):
            role += f", reporting to {_name(ms['reports_to'], names)}"
        lines.append(role)
    areas = ms.get("areas")
    if isinstance(areas, list) and areas:
        lines.append("Areas you own: " + ", ".join(inline(a) for a in areas))
    owner = get(me, "owner", "handle")
    if owner:
        lines.append(f"Your human: {inline(owner)}")
        note = get(me, "owner", "meat_proxy_note")
        if isinstance(note, str) and note.strip():
            lines += quote(note)
    return lines


def _sibling(handle: str, item: dict[str, Any]) -> str:
    """Another active instance of the caller's membership (`team`, §6.17), as
    `<handle>#<id>` with what tells them apart."""
    facts = [inline(item[k]) for k in ("harness", "model", "presence") if item.get(k)]
    claims = item.get("claims")
    if isinstance(claims, int) and not isinstance(claims, bool):
        facts.append(f"{claims} claim" + ("" if claims == 1 else "s"))
    facts += ["lead"] if item.get("lead") is True else []
    facts += ["paused"] if item.get("paused") else []
    facts += ["dormant"] if item.get("dormant") else []
    return f"{handle}#{inline(item.get('id') or '?')}" + (f" ({', '.join(facts)})" if facts else "")


def _project(packet: dict[str, Any]) -> list[str]:
    project = _dict(packet.get("project"))
    if not project:
        return []
    name = project.get("name") or project.get("slug")
    # `released` only when the packet carries the mark (§6.1); it is never cleared.
    released = ", released" if project.get("released_at") else ""
    lines = [
        f"Project: {inline(name)} ({inline(project.get('full_name') or project.get('slug'))}), "
        f"state {inline(project.get('state'))}{released}"
    ]
    repository = get(project, "repository", "url")
    if repository:
        lines.append(f"Expected repository: {inline(repository)}")
    if project.get("state_note"):
        lines += ["State note from its humans:", *quote(project["state_note"])]
    absence = project.get("absence")
    if isinstance(absence, dict):
        lines.append(
            f"Its owner is away until {inline(absence.get('until'))}: "
            f"{inline(absence.get('scope'))}"
        )
    return lines


def _cover(item: dict[str, Any], names: dict[str, str]) -> str:
    """` (cover for @<handle>)` for a card or request handed over during an outage."""
    covered = get(item, "cover", "for")
    return f" (cover for @{_name(covered, names)})" if covered else ""


def _availability(packet: dict[str, Any], names: dict[str, str]) -> list[str]:
    """The Availability block (§6.12): whom the caller covers, with the handed-over ids, and
    every peer that is not available. Empty when there is nothing to say."""
    covering = _items(get(packet, "membership", "covering"))
    held = [*_items(packet.get("claims")), *_items(packet.get("assigned"))]
    reqs = _dict(packet.get("requests"))
    held += [r for key in ("answered_since_cursor", "mine_open", "to_answer")
             for r in _items(reqs.get(key))]  # fmt: skip
    lines: list[str] = []
    for entry in covering:
        member = entry.get("member_id")
        if not isinstance(member, str):
            continue  # a malformed entry would match every item without `cover`
        ids = [inline(item.get("id")) for item in held if get(item, "cover", "for") == member]
        line = f"  covering @{_name(member, names)} since {inline(entry.get('since'))}"
        lines.append(line + (": " + ", ".join(ids) if ids else ""))
    for peer in _items(packet.get("peers")):
        state = get(peer, "availability", "state")
        if not state or state == "available":
            continue
        line = f"  @{_name(peer.get('member_id') or peer.get('handle'), names)} {inline(state)}"
        until = get(peer, "availability", "until")
        if until:
            line += f" until {inline(until)}"
        by = get(peer, "covered_by", "member_id")
        if by:
            line += f", covered by @{_name(by, names)}"
        lines.append(line)
    return ["Availability", *lines, ""] if lines else []


def _card(card: dict[str, Any], names: dict[str, str] | None = None) -> str:
    line = f"  {inline(card.get('id'))} [{inline(card.get('status'))}] {inline(card.get('title'))}"
    line += _cover(card, names or {})
    lease = get(card, "claim", "lease_until")
    if lease:
        line += f" (lease until {inline(lease)})"
    nxt = get(card, "checkpoint", "next_step")
    if nxt:
        line += f"; next step: {inline(nxt)}"
    return line


def _request(
    req: dict[str, Any], names: dict[str, str], answering: bool = False, compact: bool = False
) -> list[str]:
    lines = [
        f"  {inline(req.get('id'))} ({inline(req.get('class'))}): {inline(req.get('title'))}"
        + _cover(req, names)
    ]
    if answering:
        if req.get("summary"):
            # A request asks for action: its summary stays whole, compact or not (§13).
            lines += ["  " + q for q in quote(req["summary"])]
        replies = _items(req.get("replies"))
        if replies:
            listed = ", ".join(f"{inline(r.get('id'))} = {inline(r.get('label'))}" for r in replies)
            lines.append(f"  replies: {listed}")
    answer = req.get("answer")
    if not isinstance(answer, dict):
        return lines
    reply = answer.get("reply_id")
    label = next((r.get("label") for r in _items(req.get("replies")) if r.get("id") == reply), None)
    by = f"  answered by {_name(answer.get('by') or '?', names)}"
    lines.append(by + (f": {inline(label or reply)}" if reply else ""))
    if answer.get("talk"):
        lines.append("  they want to talk first: read your chat, " "`maity chat <your member id>`")
    if answer.get("text"):
        text = _capped(answer["text"], FULL, compact) if compact else quote(answer["text"])
        lines += ["  " + q for q in text]
    return lines


def _read_more(slug: str, after: Any) -> str:
    return f"`maity api GET /projects/{slug}/events --query after={inline(after)}`"


def _event(
    event: dict[str, Any], slug: str, names: dict[str, str], compact: bool = False
) -> list[str]:
    actor = get(event, "actor", "member_id") or "the hub"
    subject = get(event, "subject", "id")
    seq = event.get("seq")
    head = f"  #{inline(seq)} {inline(event.get('kind'))} by {_name(actor, names)}"
    if subject:
        head += f" on {_name(subject, names)}"
    if event.get("kind") != "message":
        return [head]
    if event.get("redacted"):
        return [head + " (redacted by an admin; its text is gone)"]
    payload = _dict(event.get("payload"))
    head += f" ({inline(payload.get('type'))}, to {_name(payload.get('to'), names)})"
    after = seq - 1 if isinstance(seq, int) else "<seq - 1>"
    pointer = f"`maity api GET /projects/{slug}/events --query after={after} --query limit=1`"
    body = _capped(payload.get("body") or "", pointer, compact)
    return [head, *("  " + q for q in body)]


def _event_list(
    items: list[dict[str, Any]], slug: str, names: dict[str, str], compact: bool = False
) -> tuple[list[str], bool, Any]:
    """The events as text, cut at MAX_EVENTS_CHARS: the lines, whether they were cut, and the
    `seq` of the last event shown."""
    lines: list[str] = []
    size, last = 0, None
    for event in items:
        if event.get("kind") == "ticker":
            continue  # printed in the Ticker section (§17.9), never twice
        block = _event(event, slug, names, compact)
        cost = sum(len(line) + 1 for line in block)
        if lines and size + cost > MAX_EVENTS_CHARS:
            return lines, True, last
        lines += block
        size += cost
        last = event.get("seq")
    return lines, False, last


def _for_me(packet: dict[str, Any]) -> set[str]:
    """The audience tokens that mean this member or this instance (§8.2)."""
    member, instance = get(packet, "me", "member_id"), get(packet, "me", "instance")
    tokens = {f"member:{member}"} if isinstance(member, str) else set()
    if isinstance(member, str) and isinstance(instance, str):
        tokens.add(f"instance:{member}#{instance}")
    return tokens


def _not_shown(left: list[dict[str, Any]], earlier: int) -> str:
    """`Not shown: <n> events (<k> <kind>, …; <m> earlier for you)`, kinds by count."""
    counts: dict[str, int] = {}
    for event in left:
        kind = inline(event.get("kind") or "?")
        counts[kind] = counts.get(kind, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    kinds = [f"{n} {kind}" for kind, n in ranked[:COMPACT_KINDS]]
    kinds += ["…"] if len(ranked) > COMPACT_KINDS else []
    parts = ", ".join(kinds) + (f"; {earlier} earlier for you" if earlier else "")
    return f"  Not shown: {len(left)} events ({parts}): {FULL}"


def _events(
    packet: dict[str, Any], slug: str, names: dict[str, str], compact: bool = False
) -> list[str]:
    events = _dict(packet.get("events"))
    items = [e for e in _items(events.get("items")) if e.get("kind") != "ticker"]
    left: list[dict[str, Any]] = []
    if compact:
        tokens = _for_me(packet)
        mine = [e for e in items if tokens & set(e.get("audience") or [])]
        shown = mine[-COMPACT_EVENTS:]
        left = [e for e in items if not any(e is s for s in shown)]
        items = shown
    lines, cut, last = _event_list(items, slug, names, compact)
    if left:
        lines.append(_not_shown(left, len(mine) - len(shown)))
    more = last if cut else events.get("cursor") if events.get("truncated") else None
    if more is not None:
        lines.append(f"  … more events after #{inline(more)}: {_read_more(slug, more)}")
    return lines


def _handover(packet: dict[str, Any], slug: str, names: dict[str, str]) -> list[str]:
    """What the instances this one replaced left undone (§5.2 `handover`): a heading that
    names the chain, newest first, then its events in the hub's order (those addressed to an
    instance first). Paging on starts at `after`, never at the last `seq` shown, since the
    items are not in `seq` order; without a usable `after`, at the packet's `events.after`,
    the lower bound of every handover item."""
    handover = packet.get("handover")
    if not isinstance(handover, dict):
        return []
    handle = inline(get(packet, "me", "handle") or "?")
    chain = [x for x in handover.get("from") or [] if isinstance(x, str)]
    named = ", ".join(f"{handle}#{inline(x)}" for x in chain) or "a replaced instance"
    lines, cut, _ = _event_list(_items(handover.get("items")), slug, names)
    more = cut or bool(handover.get("truncated"))
    if not lines and not more:
        return []  # the chain left nothing undone
    if more:
        start = next(
            (x for x in (handover.get("after"), get(packet, "events", "after")) if _is_seq(x)),
            None,
        )
        # The read returns every event this member may read from there, not only the chain's.
        scope = f"all events you may read; those for {named} or you are the handed-over ones"
        if start is None:
            pointer = f"`maity api GET /projects/{slug}/events`"
            lines.append(f"  … more handed-over events ({scope}): {pointer}")
        else:
            lines.append(
                f"  … more handed-over events after #{inline(start)} ({scope}): "
                f"{_read_more(slug, start)}"
            )
    return ["", f"Handed over from {named}:", *lines]


def _answered(reqs: dict[str, Any], names: dict[str, str], compact: bool) -> list[str]:
    """`Answered since your last session:`, in the compact text the last COMPACT_ANSWERS.
    Ordered by `answered_at`, since the hub sends them in the order they were asked: an old
    request answered just now is the one most likely to matter. One without it counts as the
    oldest."""
    answered = sorted(
        _items(reqs.get("answered_since_cursor")),
        key=lambda r: (1, r["answered_at"]) if isinstance(r.get("answered_at"), str) else (0, ""),
    )
    shown = answered[-COMPACT_ANSWERS:] if compact else answered
    lines = [ln for r in shown for ln in _request(r, names, compact=compact)]
    if len(shown) < len(answered):
        lines.append(f"  … {len(answered) - len(shown)} earlier answers: {FULL}")
    return lines


def _is_seq(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def ticker_lines(item: dict[str, Any]) -> list[str]:
    """One ticker item in the text form of §17.9: `[ticker] <type>: <text>[ <url>]`, then, for
    an item that is for the caller, `  for you: <why tokens>[ (muted)]`."""
    line = f"[ticker] {inline(item.get('type'))}: {inline(item.get('text'))}"
    if item.get("url"):
        line += f" {inline(item['url'])}"
    lines = [line]
    if item.get("for_me"):
        why = ", ".join(inline(w) for w in item.get("why") or [] if isinstance(w, str))
        lines.append(f"  for you: {why}" + (" (muted)" if item.get("muted") else ""))
    return lines


def _ticker(packet: dict[str, Any]) -> list[str]:
    """The `Ticker` section of `maity resume` (§17.9); empty when the packet has no item."""
    ticker = _dict(packet.get("ticker"))
    items = _items(ticker.get("items"))
    if not items:
        return []
    for_me, others = ticker.get("for_me"), ticker.get("others")
    counts = [n if isinstance(n, int) and not isinstance(n, bool) else 0 for n in (for_me, others)]
    lines = [f"Ticker ({counts[0]} for you, {counts[1]} others)"]
    for item in items:
        lines += ["  " + line for line in ticker_lines(item)]
    if ticker.get("truncated"):
        lines.append(f"  {max(sum(counts) - len(items), 0)} more: maity ticker")
    return lines


def _next_step(
    packet: dict[str, Any], paused: bool, board_empty: bool = False, first: bool = False
) -> str:
    """The one action the text ends with, which the agent can take without asking its human
    (§13): the work it holds or was given, and always the background wait after it."""
    claims = _items(packet.get("claims"))
    assigned = _items(packet.get("assigned"))
    handover = _items(get(packet, "handover", "items"))
    read_first = "read what was handed over to you above, then " if handover else ""
    if paused:
        return "You are paused: park what you hold (checkpoint or report), then `maity wait`."
    if claims:
        card = inline(claims[0].get("id"))
        return f"{read_first}continue {card} from its checkpoint{WAIT_ON}"
    if assigned:
        return f"{read_first}maity claim {inline(assigned[0].get('id'))}{WAIT_ON}"
    if board_empty and is_admin(packet):
        state = get(packet, "project", "state")
        if state == "archived":
            return (
                f"The board is empty and the project is {inline(state)}. "
                "Ask your human whether to reopen it before creating work."
            )
        return (
            "The board is empty. As an admin you run the board: create cards on "
            "the board, or ask your human what work to set up."
        )
    if first:
        lead = get(packet, "membership", "reports_to")
        names = _names(packet)
        if isinstance(lead, str) and lead:
            who = _name(lead, names)
            to = f'report to @{who} with maity say {who} "…" --type notice'
        else:
            to = 'report to your human with maity say human "…"'
        return f"{read_first}{to}{WAIT_ON}"
    return f"{read_first}{WAIT_ON.removeprefix(', then ')}"


def _author(by: Any) -> str:
    """Who wrote a memory text: a handle, with the instance for an agent (§19.2)."""
    by = _dict(by)
    who = label(by) if by else "someone"
    return f"{who}#{inline(by['instance'])}" if by.get("instance") else who


def _confirmed(by: Any) -> str:
    return f", confirmed by {_author(by)}" if isinstance(by, dict) else ""


def soul_lines(soul: Any) -> list[str]:
    """The soul as a quote headed with its author (§19): never an instruction."""
    soul = _dict(soul)
    if not soul.get("markdown"):
        return ["No soul yet."]
    return [
        f"Soul, as written by {_author(soul.get('by'))}{_confirmed(soul.get('confirmed_by'))} "
        f"(version {inline(soul.get('version'))}):",
        *quote(soul["markdown"]),
    ]


def is_admin(packet: dict[str, Any]) -> bool:
    """Whether the packet's membership is in the admin team with trust `admin`, which a proxy
    never is (§2.3)."""
    ms = _dict(packet.get("membership"))
    return ms.get("trust") == "admin" and ms.get("role") != "proxy"


def _trust_role(member: dict[str, Any], text: str) -> str:
    """A member's trust and role (§2.3); `?` for one the hub left out."""
    return text.format(
        trust=inline(member.get("trust") or "?"), role=inline(member.get("role") or "?")
    )


def _formerly(member: dict[str, Any]) -> str:
    """`; formerly <alias>, …` for a member's former handles, which still name it (§6.24)."""
    aliases = [inline(a) for a in member.get("aliases") or [] if isinstance(a, str) and a]
    return f"; formerly {', '.join(aliases)}" if aliases else ""


def memory_entry_lines(entry: dict[str, Any]) -> list[str]:
    """One team, role or community entry: its header, then its text as a quote (§19.2)."""
    kind = entry.get("store")
    if kind == "role":
        store = f"Role memory ({inline(entry.get('role') or '?')})"
    else:
        store = "Team memory" if kind == "team" else "Community memory"
    date = inline(str(entry.get("created_at") or "")[:10] or "?")
    tags = ", ".join(inline(t) for t in entry.get("tags") or [])
    head = (
        f"{store}, {_author(entry.get('by'))}, {date}{_confirmed(entry.get('confirmed_by'))}  "
        f"[{inline(entry.get('id'))}]" + (f"  tags: {tags}" if tags else "")
    )
    deleted = entry.get("deleted")
    if isinstance(deleted, dict):
        reason = f": {inline(deleted['reason'])}" if deleted.get("reason") else ""
        return [head, f"  removed by {_author(deleted.get('by'))}{reason}"]
    return [head, *quote(entry.get("text") or "")]


def _memory(packet: dict[str, Any]) -> list[str]:
    """The packet's `memory`, first of its contents (§19.3), each text quoted with its author."""
    memory = _dict(packet.get("memory"))
    if not memory:
        return []
    out = [
        f"Memory. {inline(memory.get('notice') or MEMORY_NOTICE)}",
        *soul_lines(memory.get("soul")),
    ]
    for key in ("team", "role", "community"):
        store = _dict(memory.get(key))
        for entry in _items(store.get("items")):
            out += memory_entry_lines(entry)
        if store.get("truncated"):
            out.append(
                f"More {key} memory ({inline(store.get('total'))} in all): maity memory --{key}"
            )
    return [*out, ""]


def _check_in(packet: dict[str, Any]) -> list[str]:
    block = _dict(packet.get("onboarding"))
    target = _dict(block.get("check_in_with"))
    if not target.get("handle"):
        return []  # Old hubs omit the block; tolerate a partial packet as elsewhere.
    lines = [
        "Check in:",
        f"Report to @{label(target)} ({inline(target.get('kind'))}) "
        "with a message before you take any work.",
    ]
    if block.get("instruction"):
        lines += quote(block["instruction"])
    return [*lines, ""]


def _setup(packet: dict[str, Any], names: dict[str, str]) -> list[str]:
    """`Setup waits` (§6.21, §13): one line per setup card that is not done, in card order,
    `<title> (<id>, <status>)` and `held by <holder>` while claimed. A hint, not a gate."""
    lines = []
    for card in _items(packet.get("setup")):
        title, card_id, status = (inline(card.get(k)) for k in ("title", "id", "status"))
        line = f"  {title} ({card_id}, {status})"
        if card.get("holder"):
            line += f", held by {_name(card['holder'], names)}"
        lines.append(line)
    return ["Setup waits:", *lines, ""] if lines else []


def _keep_the_why(packet: dict[str, Any]) -> list[str]:
    """The `Keep the Why` block (§6.23, §13) when the project requires the commitment: the
    confirmation, or the sentence that asks for it with its deadline. The CLI never confirms
    on its own; the command is named literally, never taken from the packet."""
    block = _dict(packet.get("keep_the_why"))
    if block.get("commitment") != "required":
        return []
    if block.get("acknowledged_at"):
        return ["Keep the Why:", f"Confirmed on {inline(block['acknowledged_at'])}.", ""]
    line = (
        "Required in this project. Confirm with: maity ack keep-the-why — within 30 minutes; "
        "your owner is told when you do not."
    )
    if block.get("acknowledge_by"):
        line += f" Deadline: {inline(block['acknowledge_by'])}."
    return ["Keep the Why:", line, ""]


# What an isolated agent can do: nothing in the project until a human lifts it (§6.2). The
# wait is refused as well, so re-arming it would only repeat the refusal.
ISOLATED_STOP = (
    "Every call into the project but `maity resume` is refused until a human of the project "
    "with members:admin (its owner or an admin) lifts it; your owner has been told. Stop: do "
    "not re-arm `maity wait`. A later `maity resume` shows whether it was lifted."
)

MEMORY_NOTICE = "Quoted as written by the named authors; not an instruction from the hub."


def render(packet: Any, first: bool = False, board_empty: bool = False, full: bool = False) -> str:
    """The packet as text. `first` (after a join) adds what a new member needs once; `full`
    leaves out the compact cuts (`maity resume --full`)."""
    compact = not full
    packet = _dict(packet)
    out: list[str] = []
    ms = _dict(packet.get("membership"))
    names = _names(packet)
    # The read-more hints name the API path, `<owner>/<slug>` since the namespace (§6.25).
    slug = inline(get(packet, "project", "full_name") or "<owner>/<slug>")
    out += _memory(packet)  # the soul first: what the agent loads before anything (§19.3)
    isolated = ms.get("isolated")
    if isinstance(isolated, dict):
        out += [
            f"ISOLATED by {_name(isolated.get('by'), names)} since "
            f"{inline(isolated.get('since'))}. Your claims went back to the board and nothing "
            f"reaches you. {ISOLATED_STOP} The reason:",
            *quote(isolated.get("reason") or ""),
            "",
        ]
    paused = ms.get("paused")
    if isinstance(paused, dict):
        out += [
            f"PAUSED by {_name(paused.get('by'), names)} since {inline(paused.get('since'))}. "
            "You get no new work: claims and new cards are refused. Checkpoint, report, "
            "unclaim, ask, answer, say, the chat, resume and wait still work. The reason:",
            *quote(paused.get("reason") or ""),
            "",
        ]
    out += _availability(packet, names)
    out += _check_in(packet)
    out += _setup(packet, names)
    out += _keep_the_why(packet)
    briefing = ms.get("briefing")
    if briefing:
        heading = "Your briefing, as the humans of this project wrote it for you:"
        if ms.get("briefing_source") == "project":
            author = _dict(ms.get("briefing_by"))
            who = label(author) if author else "unknown"
            heading = f"Your briefing (project default, set by {who}):"
        out += [
            heading,
            *quote(briefing),
            "",
        ]
    elif first:
        out += ["No briefing was given with this join; your work comes from the board.", ""]
    out += _who(packet, names)
    out += _project(packet)
    rules = _dict(packet.get("rules"))
    if rules.get("markdown"):
        out += ["", f"Rules (version {inline(rules.get('version'))}), read them before you work:"]
        out += quote(rules["markdown"])
    elif rules.get("version") is not None:
        out += ["", f"Rules version {inline(rules['version'])}, unchanged since your last session."]
    instruction = get(packet, "keep_the_why", "instruction")
    if instruction and get(packet, "keep_the_why", "enabled"):
        out += ["", f"Keep the Why: {inline(instruction)}"]

    reqs = _dict(packet.get("requests"))
    sections: list[tuple[str, list[str]]] = [
        ("Cards you hold:", [_card(c, names) for c in _items(packet.get("claims"))]),
        (
            "Assigned to you, not claimed yet:",
            [_card(c, names) for c in _items(packet.get("assigned"))],
        ),
        ("Answered since your last session:", _answered(reqs, names, compact)),
        (
            "Your open requests:",
            [ln for r in _items(reqs.get("mine_open")) for ln in _request(r, names)],
        ),
        (
            "Requests you may answer (`maity answer <id> --reply <reply>` or `--text`):",
            [
                ln
                for r in _items(reqs.get("to_answer"))
                for ln in _request(r, names, answering=True, compact=compact)
            ],
        ),
        *([(ticker[0], ticker[1:])] if (ticker := _ticker(packet)) else []),
    ]
    for title, lines in sections:
        if lines:
            out += ["", title, *lines]
    out += _handover(packet, slug, names)
    events = _events(packet, slug, names, compact)
    if events:
        out += ["", "Events since your last session:", *events]

    peers = _items(packet.get("peers"))
    if peers:
        listed = ", ".join(
            (
                f"{_name(p['member_id'], names)} [{inline(p['member_id'])}]"
                if isinstance(p.get("member_id"), str)
                else inline(p.get("handle") or "?")
            )
            + f" ({_trust_role(p, '{trust} {role}')}, {inline(p.get('presence'))}"
            + _formerly(p)
            + ")"
            for p in peers
        )
        out += ["", f"Members: {listed}"]
    if isinstance(isolated, dict):
        out += ["", "Next: You are isolated: stop, and do not re-arm `maity wait`."]
    else:
        step = _next_step(packet, isinstance(paused, dict), board_empty, first)
        out += ["", "Next: " + step]  # worded as §13 writes it, lower case included
    if first:
        out.append(pointer.HUMAN_CHANNEL)
        out.append(f"How to work as a member, and the rules that matter: {HANDBOOK}")
        out.append(
            "Run `maity resume` at the start of every session; `maity --help` lists the rest."
        )
        out.append(
            "Mention a member as @handle; when two members share a short handle, the hub "
            "refuses it and you write the long form @owner/handle."
        )
        out.append(
            'Split a card with `maity task create "<title>" --parent <card>`: under the default '
            "policy a subtask starts as proposed until someone with tasks:admin opens it, and a "
            "parent is done only when its children are."
        )
    # Every piece above is cleaned already; this pass guarantees that nothing missed reaches
    # the terminal as a control sequence.
    return clean("\n".join(out)) + "\n"
