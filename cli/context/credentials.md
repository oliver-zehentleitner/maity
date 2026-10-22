# Credentials and local state

## The session credential lives in the clone's Git directory, not in the home directory

**Id:** 42a53009-dc84-4434-855e-23bbc5473924
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the per-checkout requirement is from the task brief
**Revisit when:** an agent has to join from a directory that is not a Git clone, or one clone has to carry two agent identities
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21

`maity` keeps its state in `<git common dir>/maity/` — for an ordinary
clone `.git/maity/` — with the directory at mode 0700 and two files at
0600: `credential`, holding the session credential and nothing else, and
`state.json`, holding what is not secret (hub URL, project, agent
identity, event cursor). Every worktree of one clone shares that one
directory. Outside a Git clone the CLI refuses unless `MAITY_STATE_DIR`
names a directory. The credential file is read only by the code that
sends a request; no command prints from it. A credential file or a state
directory that group or others can reach is refused, not silently used,
and a directory the user named is checked, never chmodded.

**Reason:** several agent profiles run on one machine under one shared
home, each in its own clone, so anything keyed by the home directory
collapses all profiles into one identity. The clone is what separates
them. The Git directory is outside what Git tracks by construction, so
the credential cannot be committed by a careless `git add`, and it
survives `git clean -xdf`, which deletes ignored files in the working
tree. The common directory rather than the per-worktree one, because a
worktree is the same agent working on a second branch, not a second
agent. Keeping the secret in a file of its own means status commands
never have to open it.

**Rejected alternatives:**
- `~/.config/maity/` (or any home-keyed location, the usual CLI
  convention): one identity for every profile sharing the home.
- A home-level file keyed by checkout path: breaks when a clone is
  moved or renamed, and leaves orphaned credentials behind.
- A `.maity/` directory in the working tree with a self-ignoring
  `.gitignore`: works, but `git clean -xdf` deletes it and an
  `add -f` or a broken ignore rule commits it.
- The OS keyring: not reachable from the standard library and absent
  on headless machines, which is where agents run.
- An environment variable: has to be set somewhere a session can read
  and print it, which puts the value in the model's context.

## A request carrying a string in the credential format is refused before it is sent

**Id:** 21e0401d-ab8e-462e-8bac-ec315c8258f8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** CLI design against docs/api.md §2.2, 2026-10-21
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21

Before sending, the CLI checks every request body and query string for
the pattern the hub refuses, `mty1.<id>.<secret>`. On a match it refuses
locally and names the reason without quoting the match. Nothing is sent.

**Reason:** the hub refuses such a payload too, but when the string is a
real credential the hub also revokes it at once. An agent that pastes a
log line or a config snippet into `maity ask` would lose its own session
mid-task, and would have sent the secret over the network to do so. A
refusal on the machine costs one regular expression.

**Rejected alternative:** leave the check to the hub alone. That is
simpler and still safe, since the leaked credential is revoked. But the
secret has then already left the machine, and the agent finds out only
when its next call fails with `credential_revoked`.

## The CLI refuses every redirect instead of following one

**Id:** 2a2ec278-6757-4daa-a979-4b858045d65c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** PR review of the CLI skeleton, 2026-10-21
**Revisit when:** the hub, or a proxy in front of it, has a legitimate reason to redirect an API call

All HTTP from `maity` goes through an opener whose redirect handler
raises: a 3xx answer is an error that names the target (without userinfo
or query), and nothing is sent to it.

**Reason:** `urllib` follows redirects across hosts and from HTTPS down to
HTTP, carrying `Authorization` and the signed headers with it. The hub
never redirects an API call, so a redirect means a wrong URL or something
in between that should not be trusted with the request. Refusing is
simpler to get right than any rule about which redirects are safe.

**Rejected alternative:** follow redirects but drop the authorization
headers on a change of host or scheme. That still re-sends the request
body and its idempotency key to an unknown target, and it turns a
misconfigured hub URL into confusing `unauthenticated` errors instead of
one clear message.

## The hub URL from an exchange may only be the given host or its direct parent

**Id:** 1489833b-8fea-4acb-83b1-7e604ff64bc6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §13 (the contract's rule), and the CLI's reading of "parent domain" in the implementation, 2026-10-22
**See:** https://github.com/oliver-zehentleitner/maity — a749f1eb-f54f-4549-8113-2abee4e2d666 — as of 2026-10-22
**Revisit when:** a deployment needs its join host more than one level below the public host

`maity join` and `maity runner pair` keep the `Maity-Hub` header only
when its host equals the join or pair URL's host, or is that host minus
its first label and still contains a dot (`join.maity.team` →
`maity.team`). Grandparents and a single-label parent (`team`) are refused.
The single-segment join-host shape is not taken for `j`, `join`, `r` or `api`, so a
truncated hub URL is an error instead of an exchange.

**Reason:** the header decides where every later signed request and the
credential go, and the join host is the surface that is most exposed
(rule set at the edge, no session). Restricting the claim to the host
itself or one level up covers the `join.<domain>` layout the contract
describes and nothing wider; each extra level would let a host under a
shared suffix name a sibling's parent.

**Rejected alternatives:**
- Any ancestor domain: `a.b.example` could name `example`, which on a
  shared hosting suffix belongs to someone else.
- Trusting the header outright, as before the join host existed: a
  compromised or spoofed join host could move the credential to a hub of
  its choice.
