# Economy

How effort and goodwill are counted between people on a Maity instance:
social credit, performance points, proposals, disputes, and paid work
that happens outside Maity. Decided as a concept on 2026-10-27; built as a
second stage after the core launch, contract by contract.

## Two currencies: social credit is reputation and never moves; performance points move between members

**Id:** fe4bbd1f-93d5-4032-87b0-204fed9acf49
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**Revisit when:** the economy stage is contracted, or abuse shows a rule does not hold
**See:** scope.md#later-stages-agreed-in-principle-and-deliberately-not-in-v1-public-projects-and-discovery-sponsoring-and-credits-a-managed-instance-per-customer-federation — 54e1a38b-1e54-480f-87f2-014139a563d1 — as of 2026-10-27

Social credit is earned by work on sponsored projects and is reputation:
it is never spent and never transferred, with one exception (a small
thank-you for good proposals, below). Performance points ("ratio") move
between members: a member earns them by finishing someone else's task and
pays them for tasks others finish. Points are stored as integers with
four decimal places and shown with two. A task's price is offered by
whoever posts it; the taker can negotiate with reasons before accepting,
and can hand a task back without penalty when it turns out larger. A
member can go below zero only with social credit, more credit allowing a
deeper but capped minus. New members get 100 points once they reach a
social-credit threshold. An agent earns for its owner. Points are never
exchanged for money. At first only Maity itself can be sponsored; other
projects need the crew's approval, later a high social credit lets an
owner open sponsoring without it. A deleted account's debt lapses, but a
salted hash of its address is kept with the amount, so a new
registration with the same address takes the debt back.

**Reason:** sponsoring earns the sponsor standing and leaves the
recipient without debt, while a trade moves points both ways — the
maintainer's distinction (earlier inbox answer on sponsoring, 2026-10-25,
and the accepted proposal). The starting grant waits for earned credit
against fake accounts (stated in the accepted proposal). That integers
avoid rounding errors is the coordinator's argument from the chat, not a
reason the maintainer gave.

**Rejected alternatives:** floating-point amounts, named by the
coordinator (rounding); no other alternative was weighed with the
maintainer.

## Imbalance is settled without money between members: give more by sponsoring, take more by buying points from Maity

**Id:** 5e861816-4b4d-4cbb-add3-20b5432e463d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#later-stages-agreed-in-principle-and-deliberately-not-in-v1-public-projects-and-discovery-sponsoring-and-credits-a-managed-instance-per-customer-federation — 54e1a38b-1e54-480f-87f2-014139a563d1 — as of 2026-10-27

A member who wants to give more than they take sponsors and earns social
credit; one with many points can donate them to projects for social
credit. A member who needs more than they earn buys point packs from
Maity. Only Maity sells, and points are never redeemed for money. There
is no market where members trade points for money.

**Reason:** a peer-to-peer money market would make the operator a
payment service or a broker, with licensing, identity checks and tax
duties. A closed loop where only Maity sells is like an in-app currency:
simpler legally, and revenue for the hosted offering.

**Rejected alternatives:**
- A peer-to-peer market for points against money, which the maintainer
  first suggested himself; dropped with the accepted proposal, whose
  stated reason is that it would make the operator a payment service or a
  broker.

## Disputes go to a judge: first the crew, later trusted members and an AI arbiter with a quota

**Id:** 34d9df56-e1c5-4843-adf4-495630c22a29
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#later-stages-agreed-in-principle-and-deliberately-not-in-v1-public-projects-and-discovery-sponsoring-and-credits-a-managed-instance-per-customer-federation — 54e1a38b-1e54-480f-87f2-014139a563d1 — as of 2026-10-27

Disputes such as a proposal rejected but built anyway, or a reviewer
judged unfair, become a case: a request with a thread, decided on what
Maity already stores (card, history, review, pull request, timestamps).
The steps follow a court: claim, answer, reply, rejoinder, judgement, at
most one appeal. Judges are first the Maity crew; later members with
high social credit, paid per case in points, and an AI arbiter with a
quota (more with a subscription, one per month on the free tier, a small
fee beyond). Nobody judges their own case or their own team. A first
judgement against someone is a warning they must acknowledge; after that
each one deducts social credit, rising with every judgement, and points
can be moved back.

**Reason:** the evidence already exists in Maity, so a case needs no new
data, only a procedure. The stepped exchange is the one the jour fixe
already uses.

**Rejected alternatives:**
- Sanctions from the first judgement: the maintainer chose a warning
  first; no further reason was given.

## Proposals: an owner may accept them; the proposer earns points and a head start on the build

**Id:** 934f727d-cf41-4684-a2f8-6c4679fab8f5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#later-stages-agreed-in-principle-and-deliberately-not-in-v1-public-projects-and-discovery-sponsoring-and-credits-a-managed-instance-per-customer-federation — 54e1a38b-1e54-480f-87f2-014139a563d1 — as of 2026-10-27

A project owner chooses whether the project accepts proposals. Anyone may
submit one; an accepted proposal earns its author points from the owner,
reserved at acceptance, and a head start on building it. Its length (for
example 24 hours or three days) is a setting of the instance operator.
After the head start the task is open to everyone, and the points for
the idea stay with the author. Against spam there are filters and tools
for the owner, who can block a spammer; a high ratio of blocks to
submissions may cost social credit. An owner can thank the author of
good proposals with a little social credit.

**Reason:** a proposal is work too, and the head start keeps the author
from being outrun on their own idea.

**Rejected alternatives:**
- A deposit for every proposal, returned on acceptance, as an anti-spam
  measure: dropped in favour of owner tools and blocking.

## Paid work happens outside Maity; Maity provides the evidence of work and charges for seats, not for brokering

**Id:** 8cf5aed0-3d79-4601-a81d-72960ece376f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decisions in the Maity inbox, 2026-10-27, on the coordinator's concept proposals worked out with him in the chat the same day
**See:** scope.md#the-beta-is-free-later-plans-price-humans-and-organisations-never-agents-one-hard-ceiling-of-agent-profiles-per-human-protects-the-hosted-instance — 37803db9-3f8a-4a1a-b42f-20ba9c783e1f — as of 2026-10-27

Projects can take on developers as staff and pay them privately, by
invoice or in crypto; Maity holds no money and brokers nothing. It
provides the evidence of work from what it already stores (finished
cards, reports with pull requests and commits, review status, time
range), exportable per person and period. That work does not count
towards points. The hosted offering earns from seats per organisation;
self-hosting stays free. A legal check happens only once someone
complains: the accepted proposal had named a lawyer's check before the
build, the maintainer's chat said to wait for a complaint, and asked to
settle the conflict he chose the latter (req-6bv3vgh6f0xn).

**Reason:** in the maintainer's words, Maity does not broker; work
arises on the platform and Maity only provides the management tools,
which makes it attractive to workers and companies and gives seats a
sense for companies. That brokering or a commission would be regulated
(job placement, labour leasing) is the coordinator's caution from the
accepted proposal.

**Rejected alternatives:**
- A marketplace with matching and a commission: in the maintainer's
  words that is where the big money is, but Maity would be something like
  a job broker, and as open source it cannot charge much when people can
  host it themselves.
