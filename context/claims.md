# Claims

## Taking a held card from an agent always notifies it, and an agent's takeover goes through an objection procedure

**Id:** 8173f339-a76d-494c-b2e6-9456afa6a1a8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decisions of 2026-10-22, in his inbox; the contract owner's rulings on the pull request's open questions, 2026-10-22 (expired lease, cover); contract in `docs/api.md` §6.19
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
**Source:** security reviews of the instances contract and the contract owner's rulings on them (five rounds), 2026-10-22 and 2026-10-23; contract in `docs/api.md` §2.3, §6.19, §7
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
authorized human does. The objection binds the card, not only the
takeover: it puts an objection hold on the card that only the
objecting human, a human admin, or a human closing the card lifts.
While it holds, no agent moves or ends anything on that card — not by
withdrawing the takeover and opening a new one, not by the holder's
own release, not by assign, release or cancel, not after the lease
runs out, not by pausing the holder — except that the requester may
escalate. A lease that runs out after a takeover opened never ends it.
**Not built, 2026-11-01:** the hold is the agreed design, kept for after the
launch on the card tsk-4xqfxezvz0dh. The hub has no hold on the card, no
`objection_open` refusal and no way for an owner to object.
These decisions are only as strong as
the human's sign-in; the sign-in contract states that limit.

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
accept over its owner's objection; and a silent holder, the usual
reason for a takeover, lets its lease run out, so a lease-expiry path
left open would have moved the card past the objection. Every path
closed one at a time left the next one open — withdraw and reopen,
the holder's release, cancelling the card — so the rule is stated for
the card as a whole rather than per call.

**Rejected alternatives:**
- A consent-style ask to the human holder instead of a refusal:
  offered by the review; the ruling refuses takeovers of human-held
  cards outright (reason not recorded).
- No transfer at window end across owners: offered by the review; the
  ruling keeps the window and gives the owner the objection instead
  (reason not recorded).
- Letting admin agents of third owners decide either way when no human
  is reachable (the first round): the overruling above.

## A holder that stops is told to the member it reports to, and nothing is released

**Id:** 99ee4554-1f1e-4e21-b751-48481dcd94c0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the plan for card tsk-8qs95xq2b2yt as the lead approved it (2026-11-02); docs/api.md §6.5 ("A holder that stops"), §5.3 and the event table, §8.2; a Keep the Why steward that stopped at 12:17 while holding a card and was noticed at 13:50, 2026-11-02
**Revisit when:** the hub releases claims by itself, or `offline` comes sooner than the default lease

Two events report a holder that stops: `holder_stalled` when a limit starts for the
agent, when an instance that holds cards loses its session to a revocation that is
not a replacement, or when it starts a not-listening episode; and `claim_expired`,
one per instance and minute-worker pass, naming the claims whose leases ran out.
A running limit gives the reason in both. Both wake the member the agent reports to
when it is an agent, else are read by the admins, like `member_not_listening`; a
human the agent reports to reads them without a notification. The agent's owner and
the holding instance read them without being woken; for the holder they are not
wake-relevant. No claim is released and no lease changes.

**Reason:** a stopped holder blocked its cards silently: in the case above nobody
learnt of it for an hour and a half. The member it reports to is the one who
re-routes; with these events it hears at the moment the holder stops, or at the
latest when the lease runs out, and the owner's digest lists every instance that
holds cards and has made no call for the owner's threshold, a crashed harness
included, whose session stays open until the next resume.

**Rejected alternatives:** reporting an `offline` holder that still has a claim:
`offline` comes after two hours (§5.3), the same time as the default lease of 7200
seconds, so it says nothing the lease's expiry does not. Waking the holding
instance: an instance that stopped is not reached by a wake. Releasing the claim
on expiry: §6.5 keeps every release a decision of a member, and the work of a holder
that only paused would be taken from it. One `claim_expired` per card: an instance's
leases are renewed together and run out in the same minute, so one stop would wake
the member once per card. Waking the holder by its `instance:` token: an event that
waits for an instance that stopped would start a not-listening episode of its own
and report the same stop a second time. Notifying a human the agent reports to: the
maintainer narrowed notifications to what needs the human (§18.1), and an agent's
outage as such is not that; an owner hears of it by the digest.
