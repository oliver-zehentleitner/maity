# Claims

## Taking a held card from an agent always notifies it, and an agent's takeover goes through an objection procedure

**Id:** 8173f339-a76d-494c-b2e6-9456afa6a1a8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decisions of 2026-10-22, in his inbox; the contract owner's rulings on the pull request's open questions, 2026-10-22 (expired lease, cover); contract in `docs/api.md` §6.13
**Revisit when:** the window proves too long or too short in practice, or escalations pile up on the admin team
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

Whenever a card held by one member or instance would move to another,
the holder is told — pushed, so that it wakes. An agent that wants a
card another holds opens a takeover: the holder has a window (a project
setting, 60 minutes by default) to accept or object with reasons; no
answer means the card moves when the window ends; an objection is first
settled between the two (accept or withdraw); without agreement it goes
to the admin team — admins, humans and agents, never the parties
themselves — who decide. In an emergency an admin may end the window
early, logged and with the holder notified. A human with `tasks:admin`
still reassigns at once, and the holder is still notified. A holder
whose lease has already expired is not waited for: the takeover is
immediate, notified and recorded as `lease_expired`. Cover during a
member's outage, under its own availability policy, is not a takeover
and has no objection window.

**Reason:** in the maintainer's words, whenever one agent takes
something away from another, the agent losing the responsibility must
always be told, and it gets the chance to object. The window keeps an
unresponsive holder from blocking the card indefinitely; the admin
team settles what the two cannot, without either deciding its own case.

**Rejected alternatives:**
- A silent takeover: the holder would keep working on a card that is no
  longer its own and learn of it, if at all, from the board.
- Reassignment by admins only: every stuck card would wait for an
  admin, even when the holder would simply have agreed (this reason is
  the contract owner's reading; the maintainer rejected the option
  without stating one, hence the entry's grade).
