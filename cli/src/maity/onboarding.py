"""The resume packet as text for the agent that reads it (docs/api.md §5.2).

`maity join` and `maity resume` print this; `--json` prints the packet itself. The order is
what an agent needs first: whether it is paused, the briefing a human wrote for it, who it is,
the project, the rules, its work, what it missed, and the next step.

Nearly every string in the packet was written by someone: the briefing, messages and answers,
but also card titles, checkpoints, reply labels and display names. Two rules keep that text
from passing for this command's own output:

- every string is cleaned before it is printed (`clean`): terminal escapes, other control
  characters and bidi overrides are shown as visible escapes, so nothing can move the cursor,
  erase a line or reorder what the reader sees;
- text that may span lines is printed quoted, every line behind `> ` (`quote`), and every other
  field is collapsed onto one line (`inline`), so no field can start a line of the output.

Long text is capped in this rendering only (`MAX_BODY_*`, `MAX_EVENTS_CHARS`) with a pointer to
the full value; `--json` stays complete.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

HANDBOOK = "https://github.com/oliver-zehentleitner/maity/blob/main/docs/agents.md"
MAX_BODY_LINES = 40
MAX_BODY_CHARS = 4000
MAX_EVENTS_CHARS = 64 * 1024

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


def _capped(text: Any, pointer: str) -> list[str]:
    """`quote(text)`, cut at MAX_BODY_LINES lines or MAX_BODY_CHARS characters."""
    full = str(text)
    lines = full.rstrip("\n").split("\n")
    kept: list[str] = []
    size = 0
    for line in lines:
        if len(kept) == MAX_BODY_LINES or size + len(line) > MAX_BODY_CHARS:
            break
        kept.append(line)
        size += len(line) + 1
    if len(kept) == len(lines):
        return quote(full)
    if not kept:  # one line longer than the cap
        kept = [lines[0][:MAX_BODY_CHARS]]
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


def _names(packet: dict[str, Any]) -> dict[str, str]:
    """member id → handle, from the peers and this member itself: a human reads names. A
    handle stays out when it could be read as something else: shared by two members, shaped
    like an id or an address, or `all`; that member keeps its id."""
    pairs: list[tuple[str, str]] = []
    for member in [*_items(packet.get("peers")), _dict(packet.get("me"))]:
        member_id, handle = member.get("member_id"), member.get("handle")
        if isinstance(member_id, str) and isinstance(handle, str) and handle:
            pairs.append((member_id, handle))
    owners: dict[str, set[str]] = {}
    for member_id, handle in pairs:
        owners.setdefault(_key(handle), set()).add(member_id)
    return {
        member_id: handle
        for member_id, handle in pairs
        if len(owners[_key(handle)]) == 1
        and not _ID_SHAPED.match(_key(handle))
        and _key(handle) not in ("all", "")
    }


def _key(handle: str) -> str:
    """What a reader takes the handle for: format characters (zero-width, direction marks)
    and surrounding space dropped, case folded."""
    return "".join(c for c in handle if unicodedata.category(c) != "Cf").strip().casefold()


def _name(value: Any, names: dict[str, str]) -> str:
    """A member's handle when the packet names it, else the value as it is (an id)."""
    return inline(names.get(value, value) if isinstance(value, str) else value)


def _who(packet: dict[str, Any], names: dict[str, str]) -> list[str]:
    me, ms = _dict(packet.get("me")), _dict(packet.get("membership"))
    handle = inline(me.get("handle") or me.get("member_id") or "?")
    name = me.get("display_name")
    line = f"You are {handle}" + (f" ({inline(name)})" if name and inline(name) != handle else "")
    if me.get("member_id"):
        line += f", member id {inline(me['member_id'])}"
    lines = [line + "."]
    if ms.get("role"):
        role = f"Role: {inline(ms['role'])}"
        if ms.get("reports_to"):
            role += f", reporting to {_name(ms['reports_to'], names)}"
        lines.append(role)
    areas = ms.get("areas")
    if isinstance(areas, list) and areas:
        lines.append("Areas you own: " + ", ".join(inline(a) for a in areas))
    owner = get(me, "owner", "handle")
    if owner:
        lines.append(f"Your human: {inline(owner)}")
    return lines


def _project(packet: dict[str, Any]) -> list[str]:
    project = _dict(packet.get("project"))
    if not project:
        return []
    name = project.get("name") or project.get("slug")
    lines = [
        f"Project: {inline(name)} ({inline(project.get('slug'))}), "
        f"state {inline(project.get('state'))}"
    ]
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


def _request(req: dict[str, Any], names: dict[str, str], answering: bool = False) -> list[str]:
    lines = [
        f"  {inline(req.get('id'))} ({inline(req.get('class'))}): {inline(req.get('title'))}"
        + _cover(req, names)
    ]
    if answering:
        if req.get("summary"):
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
        lines.append(
            "  they want to talk first: read your chat, "
            "`maity api GET /projects/<slug>/conversations/<your member id>/messages`"
        )
    if answer.get("text"):
        lines += ["  " + q for q in quote(answer["text"])]
    return lines


def _read_more(slug: str, after: Any) -> str:
    return f"`maity api GET /projects/{slug}/events --query after={inline(after)}`"


def _event(event: dict[str, Any], slug: str, names: dict[str, str]) -> list[str]:
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
    return [head, *("  " + q for q in _capped(payload.get("body") or "", pointer))]


def _events(packet: dict[str, Any], slug: str, names: dict[str, str]) -> list[str]:
    events = _dict(packet.get("events"))
    lines: list[str] = []
    size, last = 0, None
    for event in _items(events.get("items")):
        block = _event(event, slug, names)
        cost = sum(len(line) + 1 for line in block)
        if lines and size + cost > MAX_EVENTS_CHARS:
            return [*lines, f"  … more events after #{inline(last)}: {_read_more(slug, last)}"]
        lines += block
        size += cost
        last = event.get("seq")
    if events.get("truncated"):
        cursor = events.get("cursor")
        lines.append(f"  … more events after #{inline(cursor)}: {_read_more(slug, cursor)}")
    return lines


def _next_step(packet: dict[str, Any], paused: bool) -> str:
    claims = _items(packet.get("claims"))
    assigned = _items(packet.get("assigned"))
    if paused:
        return "You are paused: park what you hold (checkpoint or report), then `maity wait`."
    if claims:
        card = inline(claims[0].get("id"))
        return f"Continue {card} from its checkpoint; `maity wait` when nothing is left."
    if assigned:
        return f"`maity claim {inline(assigned[0].get('id'))}`, the card assigned to you."
    return "`maity wait` until something is addressed to you."


def render(packet: Any, first: bool = False) -> str:
    """The packet as text. `first` (after a join) adds what a new member needs once."""
    packet = _dict(packet)
    out: list[str] = []
    ms = _dict(packet.get("membership"))
    names = _names(packet)
    slug = inline(get(packet, "project", "slug") or "<slug>")
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
    briefing = ms.get("briefing")
    if briefing:
        out += [
            "Your briefing, as the humans of this project wrote it for you:",
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
        (
            "Answered since your last session:",
            [ln for r in _items(reqs.get("answered_since_cursor")) for ln in _request(r, names)],
        ),
        (
            "Your open requests:",
            [ln for r in _items(reqs.get("mine_open")) for ln in _request(r, names)],
        ),
        (
            "Requests you may answer (`maity answer <id> --reply <reply>` or `--text`):",
            [
                ln
                for r in _items(reqs.get("to_answer"))
                for ln in _request(r, names, answering=True)
            ],
        ),
        ("Events since your last session:", _events(packet, slug, names)),
    ]
    for title, lines in sections:
        if lines:
            out += ["", title, *lines]

    peers = _items(packet.get("peers"))
    if peers:
        listed = ", ".join(
            (
                f"{_name(p['member_id'], names)} [{inline(p['member_id'])}]"
                if isinstance(p.get("member_id"), str)
                else inline(p.get("handle") or "?")
            )
            + f" ({inline(p.get('role'))}, {inline(p.get('presence'))})"
            for p in peers
        )
        out += ["", f"Members: {listed}"]
    out += ["", "Next: " + _next_step(packet, isinstance(paused, dict))]
    if first:
        out.append(f"How to work as a member, and the rules that matter: {HANDBOOK}")
        out.append(
            "Run `maity resume` at the start of every session; `maity --help` lists the rest."
        )
    # Every piece above is cleaned already; this pass guarantees that nothing missed reaches
    # the terminal as a control sequence.
    return clean("\n".join(out)) + "\n"
