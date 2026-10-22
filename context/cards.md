# Cards

## Cards carry links, an edit history and notes; a note never changes the card

**Id:** 4e1208f1-4ca9-45ad-9005-3327b2638a0c
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision, 2026-10-22; contract change in `docs/api.md` §6.11–§6.14
**Revisit when:** a second forge is probed, a note needs to be edited or withdrawn by its author, or the holder of a card needs to resolve notes on it

A card carries three things beyond its own text. **Links**: references
to forge issues and pull requests of the project's repository owner, or
to any `https` URL. For a forge link the hub reads title and state
itself through the probe and keeps them current; it never takes a title
from the client. A card can be created from a forge issue, with the
issue's text quoted as untrusted text. **History**: every edit of a
card's fields is kept with who, when, and the value before and after,
text included, so that an owner or admin editing any card on the board
leaves a trace. **Notes**: any member who can read a card may attach a
remark to it. A note never changes the card; the owner or an admin marks
it incorporated or dismissed, and the holder and creator are told of a
new one. Whether the card's creator may mark notes too was left open by
the maintainer; the contract proposes it. Agents may add notes and links on every
card they can see and edit only the cards they hold or created, unless
they hold `tasks:admin`.

**Reason:** the decision is the maintainer's; the reason was not stated
with it and is inferred from `trust.md` and `integrations.md`. A card is the instruction its holder works from. If every
member could edit it, an agent's work could be redirected by any other
member; if nobody but the holder and admins could say anything about it,
remarks would go to messages and be lost with the conversation. Notes
keep the remark next to the card without giving its author authority
over it (`trust.md`). Forge state shown on the board is observed rather than typed for the
same reason the release gate is (`integrations.md`).

**Rejected alternative:** a client-sent title and state on a forge link.
Rejected because the board would then show whatever was typed as if it
were the forge's state.

**Rejected alternative:** members other than holder, creator and admins
changing the card's text directly. Rejected for the reason above: notes
carry the remark, an editor works it in.

**See:** integrations.md#a-read-only-forge-probe-in-v1-observed-pr-check-and-tag-state-next-to-agent-claims — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-22
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22
