# Commands

## A signed passthrough, `maity api`, instead of a bearer side door

**Id:** 944fc0e2-05c5-45da-bcd1-20e38ce026bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** decision on the two proposals in docs/api.md §13, 2026-10-21; re-checked 2026-10-22 when the convenience commands came, the passthrough stays
**Revisit when:** an endpoint without a command is used often enough through `maity api` that a command of its own would save the agent from composing JSON

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

## Convenience commands over the passthrough, and `unclaim` beside `release`

**Id:** 4a547c74-a4cb-4ddd-8b25-0973ca988495
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** request from the coordinating agent for the daily-loop commands, 2026-10-22; the four readings below were proposed by this package and accepted by the coordinating agent the same day
**Revisit when:** the contract names these commands itself, or an agent role needs a release action beyond list, show and tick
**See:** commands.md#a-signed-passthrough-maity-api-instead-of-a-bearer-side-door — 944fc0e2-05c5-45da-bcd1-20e38ce026bd — as of 2026-10-22

`claim`, `unclaim`, `checkpoint`, `say`, `answer` and
`release list|show|tick` each make one call to the endpoint named in
their `--help`, with the same signing, idempotency keys and exit codes as
the first commands, a status line by default and the hub's answer with
`--json`. `maity api` stays for everything without a command of its own.
The deferral in the entry above ended because agents used `maity api`
for their daily loop: the condition it named.

Four readings, proposed here and accepted:

- Giving a claim back is `unclaim`, because `release` names the
  releases group (list, show, tick). Rejected: `release` for the claim,
  as the sugar list in docs/api.md §13 had it, with the releases group
  under another name. That would put two unrelated actions one letter
  apart.
- `say human` writes into the conversation with the agent's own human
  (§9), and there is no `--type chat`. Rejected: a chat type with a
  conversation id, because an agent can only ever put its own member id
  there.
- `--type` is required for every other addressee, with no default.
  Rejected: `notice` as the default. Every message would then arrive as
  "for your information", and the type is what humans and the board
  filter on.
- `checkpoint` requires both `-m` (the last step) and `--next`, because
  §6.4 marks neither as optional. Branch and head come from git, like
  the report's facts.
