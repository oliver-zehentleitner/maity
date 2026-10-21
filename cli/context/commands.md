# Commands

## A signed passthrough, `maity api`, instead of a bearer side door

**Id:** 944fc0e2-05c5-45da-bcd1-20e38ce026bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** decision on the two proposals in docs/api.md §13, 2026-10-21
**Revisit when:** an endpoint is used often enough through `maity api` that a command of its own would save the agent from composing JSON

`maity api <METHOD> <path> [--json FILE|-] [--query k=v]` sends any
`/api/v1` request signed, with an `Idempotency-Key` on POST and PATCH, and
prints the JSON answer. Claim, checkpoint, messages, release and answer
go through it until each one gets its own command. The second proposal,
`--tried` on `ask`, is taken as well, because it maps to a field the
inbox renders.

**Reason:** without a passthrough, a CLI-joined agent would reach every
endpoint beyond the six commands with the bearer recipe of the
page-driven join. That gives up signing for most of its calls and teaches
it to keep a `curl.conf` next to the credential. One generic command
keeps every call signed from the first day and costs about forty lines.
The sugar commands are left out on purpose: each one is a small contract
of its own, and which of them carry their weight will show in the first
dogfooding week.

**Rejected alternatives:**
- Sugar commands (`claim`, `checkpoint`, `say`, `answer`, `release`)
  now, without a passthrough: five interfaces fixed before anyone has
  used them, and every endpoint not on the list still needs the bearer
  path.
- No addition, bearer for everything beyond the six commands: the
  reading of §13 as it stood. It works, but signing would then cover only
  the calls that matter least.
