"""The resume packet as text for the agent that reads it (docs/api.md §5.2).

`maity join` and `maity resume` print this; `--json` prints the packet itself. The order is
what an agent needs first: whether it is paused, the briefing a human wrote for it, who it is,
the project, the rules, its work, what it missed, and the next step.

Text that people wrote (the briefing, messages, answers, card titles) is printed quoted, every
line behind `> `, and labelled with who wrote it. It is data from those people, never output of
the hub or of this command, and the quoting keeps it from passing for either.
"""

from __future__ import annotations

from typing import Any

HANDBOOK = "https://github.com/oliver-zehentleitner/maity/blob/main/docs/agents.md"
QUOTED_KINDS = ("message",)


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _items(data: Any) -> list[dict[str, Any]]:
    return [i for i in data if isinstance(i, dict)] if isinstance(data, list) else []


def quote(text: str) -> list[str]:
    """Every line of `text` behind `> `, so nothing in it reads as a line of this output."""
    lines = str(text).rstrip("\n").splitlines() or [""]
    return [f"> {line}".rstrip() for line in lines]


def _who(packet: dict[str, Any]) -> list[str]:
    me, ms = packet.get("me") or {}, packet.get("membership") or {}
    name = me.get("display_name")
    handle = me.get("handle") or me.get("member_id") or "?"
    line = f"You are {handle}" + (f" ({name})" if name and name != handle else "")
    line += f", member id {me.get('member_id')}" if me.get("member_id") else ""
    lines = [line + "."]
    role = ms.get("role")
    if role:
        lines.append(
            f"Role: {role}" + (f", reporting to {ms['reports_to']}" if ms.get("reports_to") else "")
        )
    areas = ms.get("areas")
    if areas:
        lines.append("Areas you own: " + ", ".join(map(str, areas)))
    owner = _get(me, "owner", "handle")
    if owner:
        lines.append(f"Your human: {owner}")
    return lines


def _project(packet: dict[str, Any]) -> list[str]:
    project = packet.get("project") or {}
    if not project:
        return []
    name = project.get("name") or project.get("slug")
    lines = [f"Project: {name} ({project.get('slug')}), state {project.get('state')}"]
    if project.get("state_note"):
        lines += ["State note from its humans:", *quote(project["state_note"])]
    absence = project.get("absence")
    if isinstance(absence, dict):
        lines.append(f"Its owner is away until {absence.get('until')}: {absence.get('scope')}")
    return lines


def _card(card: dict[str, Any]) -> str:
    line = f"  {card.get('id')} [{card.get('status')}] {card.get('title')}"
    lease = _get(card, "claim", "lease_until")
    if lease:
        line += f" (lease until {lease})"
    nxt = _get(card, "checkpoint", "next_step")
    if nxt:
        line += f"; next step: {nxt}"
    return line


def _request(req: dict[str, Any]) -> list[str]:
    head = f"  {req.get('id')} ({req.get('class')}): {req.get('title')}"
    answer = req.get("answer")
    if not isinstance(answer, dict):
        return [head]
    by = answer.get("by") or "?"
    reply = answer.get("reply_id")
    label = next((r.get("label") for r in _items(req.get("replies")) if r.get("id") == reply), None)
    lines = [head, f"  answered by {by}" + (f": {label or reply}" if reply else "")]
    if answer.get("talk"):
        lines.append(
            "  they want to talk first: read your chat, "
            "`maity api GET /projects/<slug>/conversations/<your member id>/messages`"
        )
    if answer.get("text"):
        lines += ["  " + q for q in quote(answer["text"])]
    return lines


def _event(event: dict[str, Any]) -> list[str]:
    actor = _get(event, "actor", "member_id") or "the hub"
    subject = _get(event, "subject", "id")
    head = f"  #{event.get('seq')} {event.get('kind')} by {actor}" + (
        f" on {subject}" if subject else ""
    )
    if event.get("kind") in QUOTED_KINDS:
        payload = event.get("payload") or {}
        head += f" ({payload.get('type')}, to {payload.get('to')})"
        return [head, *("  " + q for q in quote(payload.get("body") or ""))]
    return [head]


def _next_step(packet: dict[str, Any], paused: bool) -> str:
    claims = _items(packet.get("claims"))
    assigned = _items(packet.get("assigned"))
    if paused:
        return "You are paused: checkpoint what you hold, then `maity wait` for the lift."
    if claims:
        card = claims[0].get("id")
        return f"Continue {card} from its checkpoint; `maity wait` when nothing is left."
    if assigned:
        return f"`maity claim {assigned[0].get('id')}`, the card assigned to you."
    return "`maity wait` until something is addressed to you."


def render(packet: dict[str, Any], first: bool = False) -> str:
    """The packet as text. `first` (after a join) adds what a new member needs once."""
    out: list[str] = []
    ms = packet.get("membership") or {}
    paused = ms.get("paused")
    if isinstance(paused, dict):
        out += [
            f"PAUSED by {paused.get('by')} since {paused.get('since')}. You get no new work "
            "(claims and new cards are refused); checkpoint, report, unclaim, ask and say still "
            "work. The reason:",
            *quote(paused.get("reason") or ""),
            "",
        ]
    briefing = ms.get("briefing")
    if briefing:
        out += [
            "Your briefing, as the humans of this project wrote it for you:",
            *quote(briefing),
            "",
        ]
    elif first:
        out += ["No briefing was given with this join; your work comes from the board.", ""]
    out += _who(packet)
    out += _project(packet)
    rules = packet.get("rules") or {}
    instruction = _get(packet, "keep_the_why", "instruction")
    if rules.get("markdown"):
        out += ["", f"Rules (version {rules.get('version')}), read them before you work:"]
        out += quote(rules["markdown"])
    elif rules.get("version") is not None:
        out += ["", f"Rules version {rules.get('version')}, unchanged since your last session."]
    if instruction and _get(packet, "keep_the_why", "enabled"):
        out += ["", f"Keep the Why: {instruction}"]

    sections: list[tuple[str, list[str]]] = [
        ("Cards you hold:", [_card(c) for c in _items(packet.get("claims"))]),
        ("Assigned to you, not claimed yet:", [_card(c) for c in _items(packet.get("assigned"))]),
    ]
    reqs = packet.get("requests") or {}
    for title, key in (
        ("Answered since your last session:", "answered_since_cursor"),
        ("Your open requests:", "mine_open"),
        ("Requests you may answer:", "to_answer"),
    ):
        sections.append((title, [line for r in _items(reqs.get(key)) for line in _request(r)]))
    events = packet.get("events") or {}
    missed = [line for e in _items(events.get("items")) for line in _event(e)]
    if events.get("truncated"):
        slug = _get(packet, "project", "slug") or "<slug>"
        missed.append(
            f"  … more after #{events.get('cursor')}: "
            f"`maity api GET /projects/{slug}/events --query after={events.get('cursor')}`"
        )
    sections.append(("Events since your last session:", missed))
    for title, lines in sections:
        if lines:
            out += ["", title, *lines]

    peers = _items(packet.get("peers"))
    if peers:
        listed = ", ".join(
            f"{p.get('handle') or p.get('member_id')} ({p.get('role')}, {p.get('presence')})"
            for p in peers
        )
        out += ["", f"Members: {listed}"]
    out += ["", "Next: " + _next_step(packet, isinstance(paused, dict))]
    if first:
        out.append(f"How to work as a member, and the rules that matter: {HANDBOOK}")
        out.append(
            "Run `maity resume` at the start of every session; `maity --help` lists the rest."
        )
    return "\n".join(out) + "\n"
