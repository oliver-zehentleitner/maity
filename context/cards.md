# Cards

## Cards carry links, an edit history and notes; a note never changes the card

**Id:** 4e1208f1-4ca9-45ad-9005-3327b2638a0c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision, 2026-10-22, with the contract owner's rulings of 2026-10-22; contract in `docs/api.md` (card links, import, edit history, notes)
**Revisit when:** a second forge is probed, a note needs to be edited or withdrawn by its author, or the holder of a card needs to resolve notes on it
**See:** integrations.md#a-read-only-forge-probe-in-v1-observed-pr-check-and-tag-state-next-to-agent-claims — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-22
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

A card carries three things beyond its own text. **Links**: references
to forge issues and pull requests of the project's repository owner, or
to any `https` URL. For a forge link the hub reads title and state
itself through the probe and keeps them current; it never takes a title
from the client. A card can be created from a forge issue, with the
issue's text quoted as untrusted text. **History**: every edit of a
card's fields is kept with who, when, and the value before and after,
text included, so that an owner or admin editing any card on the board
leaves a trace. **Notes**: any member who can read a card may attach a
remark to it. A note never changes the card; the owner, an admin or the
card's creator marks it incorporated or dismissed, and the holder and
creator are told of a new one. Agents may add notes and links on every
card they can see and edit only the cards they hold or created, unless
they hold `tasks:admin`.

The contract owner's rulings settled the points the decision left open:
the card's creator may resolve notes, its holder may not; a note is
never edited or withdrawn, a wrong one is dismissed; forge links stay at
the project repository's host and owner, and an item the hub cannot read
shows as not found; CLI commands for notes and links come as a
follow-up, `maity api` reaches them until then.

**Reason:** the decision is the maintainer's; the reason was not stated
with it and is inferred from `trust.md` and `integrations.md`. A card is
the instruction its holder works from. If every member could edit it, an
agent's work could be redirected by any other member; if nobody but the
holder and admins could say anything about it, remarks would go to
messages and be lost with the conversation. Notes keep the remark next
to the card without giving its author authority over it (`trust.md`).
Forge state shown on the board is observed rather than typed for the
same reason the release gate is (`integrations.md`).

**Rejected alternatives:**
- A client-sent title and state on a forge link: the board would then
  show whatever was typed as if it were the forge's state.
- Members other than holder, creator and admins changing the card's text
  directly: notes carry the remark, an editor works it in.
- The holder resolving notes on its card: ruled out by the contract
  owner; the reason was not stated with the ruling (unknown).
