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
