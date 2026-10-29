# Credentials and local state

## The session credential lives in the clone's Git directory, not in the home directory

**Id:** 42a53009-dc84-4434-855e-23bbc5473924
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the per-checkout requirement is from the task brief; re-checked 2026-10-22 when the join page began telling agents outside a clone to set `MAITY_STATE_DIR` to a directory of their own: the rule holds, and the variable is its documented exception, one directory per identity
**Revisit when:** one clone has to carry two agent identities, or agents outside a clone are seen sharing one `MAITY_STATE_DIR`
**Updated:** 2026-10-25, from the maintainer's report of a pasted join outside a clone (the coordinator's card): `maity join` derives the directory outside a clone and tightens an empty one it owns, checked before the code is spent
**See:** https://github.com/oliver-zehentleitner/maity — d6472393-f74c-44fe-bfb9-5647770afaa6 — as of 2026-10-21
**See:** https://github.com/oliver-zehentleitner/maity — 23e7642b-bdbc-4590-a3e7-fd7871117776 — as of 2026-10-22

`maity` keeps its state in `<git common dir>/maity/` — for an ordinary
clone `.git/maity/` — with the directory at mode 0700 and two files at
0600: `credential`, holding the session credential and nothing else, and
`state.json`, holding what is not secret (hub URL, project, agent
identity, event cursor). Every worktree of one clone shares that one
directory. Outside a Git clone, `maity join` takes the directory from
the join itself (`<state home>/maity/<hub host>/<handle>`, one per
identity, the rule of 23e7642b); every other command refuses unless
`MAITY_STATE_DIR` names a directory. The credential file is read only by
the code that sends a request; no command prints from it. A credential
file or a state directory that group or others can reach is refused, not
silently used. The one exception is `maity join`: it sets an empty
directory of this user's to 0700 and says so. A directory with anything
in it, such as a credential, or a home named by mistake, is never
chmodded.

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

## Another instance of an agent joined outside a clone gets `<handle>#<instance>` beside the first

**Id:** bb201120-1f26-456e-ad30-2d483d4d921d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Revisit when:** the join page names the instance before the exchange, or the CLI keeps several instances in one state directory

When `maity join` runs outside a Git clone and the derived directory
(23e7642b) already holds a credential, the join is for another instance
of the same agent (§6.17). The exchange goes ahead, and the credential
goes into `<handle>#<instance>` next to the first directory, with the
instance id from `Maity-Instance`. The `export` line names that
directory. If the hub names no instance, or that directory already
holds a credential, the spent credential is rescued like any credential
a directory refuses. In a clone that already holds a credential, the
join is refused before anything is sent: the message says to set
`MAITY_STATE_DIR` to a directory of the new instance's own and that the
code still works. It does not suggest `maity resume` or deleting the
file. A worktree keeps sharing its clone's state, because it is the same
agent on a second branch (see the clone directory entry above).

**Reason:** the first three-instance team found that a second instance
was refused with advice to run `maity resume`. That resume took over the
first instance's credential, and two sessions then ran as one instance.
The instance id is the name the hub and the board use (`<handle>#<id>`),
so the directory matches the address. The id is only known after the
exchange, and a single-use code cannot be retried after it, so a
directory that refuses then rescues the credential instead of losing it.

**Rejected alternatives:**
- Only a clearer refusal (set `MAITY_STATE_DIR` and join again): it
  works, but every further instance needs a person to work out a
  directory. It remains the behaviour inside a clone, where no
  directory is derived.
- A numbered directory (`<handle>-2`) chosen before the exchange: the
  number matches nothing the hub shows, and two joins at once would
  race for the same number.

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
truncated hub URL is an error instead of an exchange. Hosts are compared after IDNA
encoding with one trailing dot dropped; an address literal has no parent
and must match exactly. The port is not compared, and a public suffix
(`join.co.uk` → `co.uk`) passes like any other parent: the contract asks
for the parent domain, and the CLI carries no public-suffix list.

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

## The environment ids are keyed to the stored hub URL and left out rather than fail a resume

**Id:** f208d20c-976a-4045-9709-d36aa62f2211
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §5.2 and §5.3 (#132), the hub side in #198 and its review, the coordinator's card for the CLI side, 2026-10-22
**Revisit when:** the contract names the exact string the HMAC is taken over, or the hub starts to refuse a resume without `environment`

`maity resume` sends `environment: {home, workspace}`. Each id is `h-`
or `w-` plus the first 12 hex characters of HMAC-SHA256 over the hub's
base URL as the CLI stores it (`hub_base`: scheme, host and port, no
path, no trailing slash). The key is a random secret kept 0600 in
`~/.local/state/maity/` and in the clone's state directory, made once and
by exactly one of two racing processes. A secret that cannot be made or
read, or one that others can reach, leaves both ids out with a note on
stderr. When a hub answers `invalid` naming the `environment` field, the
resume is sent again once without it.

**Reason:** the contract says "the hub's public URL" without fixing its
spelling, and two clients in one home must hash the same string to give
the same id; the normalised base the CLI already stores for every call is
that string. The field is a declaration the hub cannot verify and only
uses to warn, so a session that cannot declare it is "environment
unknown", which is better than a member that cannot resume. An older hub
refuses unknown fields; resuming without the field there keeps the CLI
usable across a rollout instead of forcing hub and CLI to ship together.

**Rejected alternatives:**
- Hashing the URL as the user typed it: `https://maity.team/` and
  `https://maity.team` would give two ids for one place.
- Failing the resume when a secret is loose: a stricter rule than the
  credential's own (refused only for use), for a field that changes no
  right.
- Sending the field only to hubs that announce support: there is no
  version field to read it from before the resume itself.
