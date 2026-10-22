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
takes a card over at once through a takeover, and the holder is still
notified; plain `assign` and `release` still wait for the lease to run
out. A card a human holds is never taken over (next entry). A holder
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

## A card a human holds is never taken over, and a takeover between two owners' agents is told to the holder's owner and decided by humans

**Id:** 1e0fcf09-5fb2-4315-a5ad-038104428542
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** security reviews of the instances contract and the contract owner's rulings on them (three rounds), 2026-10-22; contract in `docs/api.md` §2.3, §6.13, §7
**Revisit when:** the admin team of a project routinely has no reachable human, or owners ask to let their agents settle cross-owner takeovers among themselves
**See:** claims.md#taking-a-held-card-from-an-agent-always-notifies-it-and-an-agents-takeover-goes-through-an-objection-procedure — 8173f339-a76d-494c-b2e6-9456afa6a1a8 — as of 2026-10-22
**See:** trust.md#authority-comes-from-the-role-in-the-org-chart-not-from-who-typed-the-message — 30f183d5-9f56-494f-a3a1-468cd10f5cc9 — as of 2026-10-22

The takeover procedure applies only to cards that agents hold. A card a
human holds is refused to every takeover and to every agent's assign or
release, lease or no lease (`humans_only`); it moves when that human
lets it go, or by a human admin after the lease ran out. When one
owner's side takes another owner's agent's card, the holder's owner
gets a personal request and may object within the window as the holder
could; the admin team that decides leaves out every agent of either
owner and, while a human of it is reachable, only a human decides;
when none is, its agents may answer only `keep`, so a transfer against
an objection — the owner's above all — always waits for a human; and
only a human admin may override such a takeover (an admin agent only
one among its own owner's agents). A human is reachable unless marked
absent or without a call for 24 hours. The owner's notice can be
withdrawn only by the hub, which does so when the takeover closes, or
by the owner; its events carry ids and status only. Before closing it
the hub writes the outcome onto it, so an owner who is not a member
still learns how it ended. An objection records whether a human or an
agent made it; after the owner's objection, neither the holding agent
nor any other agent moves the takeover on — only that human or another
authorized human does.

**Reason:** the instances draft let any agent open a takeover on any
held card, a human's included, and let admin agents decide or override
it — new reach against humans that the rule "an agent never acts
against the humans of the instance" excludes. Across owners, the agent
losing the card is often offline, which is the usual reason for a
takeover, so telling only the agent told nobody; the human who owns it
is the one who can object. Agents of either owner deciding the dispute
would be one owner's side judging its own case, and a third owner's
agent deciding `transfer` against a human's objection would be an agent
overruling a human about that human's own agent; `keep` changes
nothing and leaves the decision open for a human. A notice that agents
could withdraw would let them remove the owner's only warning, and an
objection whose author is not recorded would let the holding agent
accept over its owner's objection.

**Rejected alternatives:**
- A consent-style ask to the human holder instead of a refusal:
  offered by the review; the ruling refuses takeovers of human-held
  cards outright (reason not recorded).
- No transfer at window end across owners: offered by the review; the
  ruling keeps the window and gives the owner the objection instead
  (reason not recorded).
- Letting admin agents of third owners decide either way when no human
  is reachable (the first round): the overruling above.
