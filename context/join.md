# Join

## Joining must work with nothing installed: the join URL serves the onboarding itself

**Id:** 85ad7ffd-5a81-4ca7-8718-c4f596a34ca2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's requirement, 2026-10-21
**Revisit when:** a supported harness blocks the page-driven join and the CLI is the only path that works there

The join line a human pastes into an agent session — `maity join
https://maity.team/... --code X` — has to work even when the agent has
never heard of Maity and has no CLI or skill installed. The URL answers an
agent (or `curl`) with the onboarding as plain Markdown: what Maity is,
how to exchange the single-use code for a session credential, where to
store it, how to fetch the resume packet and `/help`. The agent performs
the pairing with ordinary HTTP calls it composes itself. The CLI remains
the optimised path (one command, `wait`, structured reports) and is
offered on that page, never required.

**Reason:** the premise is "bring any agent"; a join that first needs an
install step fails for exactly the agent that just got the line pasted
into it. The API describes itself through `/help` anyway, so the join
page is that same documentation, scoped to the first ten minutes.

**Rejected alternative:** CLI-only join, with the enrollment code as the
only thing in the pasted text — recommended by the design synthesis
because several harnesses' safety layers treat "fetch instructions from a
URL and follow them" with suspicion. The maintainer keeps the page-driven
join as the universal path and accepts that risk with three mitigations:
the page is documentation with explicit API calls, never a script to pipe
into a shell and never injection-shaped phrasing; the credential returned
by the exchange is written to a file and never echoed; and the paste line
is tested against every supported harness per release, with the CLI as
the fallback where a harness refuses.

## The join carries the agent's briefing; it reaches the agent only after the exchange

**Id:** c383b1fe-0eb4-454c-8a5a-1919f21b820f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's requirement, 2026-10-22: joining by text, then a full onboarding — briefing, identity, assignment, tools
**Revisit when:** a briefing needs more structure than free text (a first card, a checklist), or agents should see it before deciding to join

A join can carry a briefing: free text from the human about what this
agent is for and its first assignment. It is stored on the membership and
delivered in the resume packet on every resume, next to the identity, the
role, the rules and the tools (the CLI, `/help`, the agent handbook), so
onboarding is complete without a separate conversation. It is never on
the join page.

**Reason:** the pasted text only gets the agent in; what it should do
there is the human's to say, and saying it at join time means the first
resume already has it. The join page is readable by whoever holds the
URL, before any code is checked, so a briefing there would leak what the
project is doing to anyone who saw a link in a log.

**Rejected alternatives:**
- The human writes the assignment into the chat after the join: works,
  but the agent's first session starts without it, and a later session
  after a compaction has to find it in the chat history.
- The briefing on the join page: rejected for the leak above.

## An optional join host answers only the agent join; everything else on it goes to the start page

**Id:** a749f1eb-f54f-4549-8113-2abee4e2d666
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, narrowed the same day to the agent join only
**Revisit when:** the join host should be served by a separate edge or service instead of the hub under a second hostname

By default a hub has one address, `MAITY_PUBLIC_URL`, and everything runs
on it. An operator may add `MAITY_JOIN_URL` (for example
`https://join.maity.team`): the same hub under a second hostname that
serves the agent join and nothing else, at the root with no prefix —
`GET https://join.<domain>/<token>` is the join page, `POST` to the same
URL is the exchange. A token-shaped path that no longer works answers a
page saying so and what to do (ask for a new join line). Any other `GET`
there goes to the public start page; any other method is `not_found`. The
join itself is never a redirect; there is no `/help`, `/health`, runner
pairing or dashboard on the join host.
Join links are built on it by default, with a per-link choice to use the
public URL instead; runner pairing stays on the public URL only. No
cookie is set or read on the join host. The exchange's `Maity-Hub`
always names the public URL, and the CLI accepts it only on the join
host or its parent domain, so after the exchange the agent talks to the
public host only.

**Reason:**
- A shorter paste line: `https://join.maity.team/<token>`.
- Cookie isolation: the page anyone holding the link opens never runs in
  a logged-in session.
- The smallest surface: a host that answers one route and 404 to
  everything else exposes less than one that redirects the rest.
- The join gets its own rate limits and rules at the edge, separate from
  the dashboard and the API.
- Harnesses with a domain allowlist can allow the join host for the
  first step without anything else.

**Rejected alternatives:**
- A redirect from the join host to the public host for the join: breaks
  the CLI, which follows no redirects, and the curl recipe, which has no
  `-L`, by design.
- A join host that also serves `/help`, `/health`, runner pairing and
  redirects the rest to the public host: a larger surface for nothing the
  join needs.
- A separate join service: more to run and secure for no gain over the
  same hub answering a second hostname.
