# Idempotency keys

Why `Idempotency-Key` (`docs/api.md` §1.5, `maity_hub/idempotency.py`) is
built the way it is.

## A key replays only the call it was first used for: method, route, resource and body

**Id:** be28183d-90cd-4acd-b043-59819643f89d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review of the card import (#271), where a key reused in another project replayed the first project's resource; the coordinator's ruling of 2026-10-29 to fix it apart from the import, as a security fix, with the project named by its id
**Revisit when:** keys are scoped by something other than the caller, or a resource gets more than one route that writes the same thing

A key is unique per caller (§1.5), and a human's spans every project they
are in. With only the body hashed, the same key and body sent to another
project's route replayed the resource the first project's call had made:
the caller got another project's card back, and the second call never ran.
The stored hash now covers the method, the route's template, its path
parameters and the body. The project parameter counts by the project's id,
resolved through `namespace.resolve`, so a call through an old name of the
project (`project_alias`, §6.25) is the same call as through its current
name, and a repeat after a rename still replays. Any other difference is
`idempotency_mismatch`. The query string is not part of the hash: no
create or update route takes one, and the only mutating route with a
query parameter (`DELETE /agents/{id}?cascade`) is idempotent by itself,
so a key there is optional (§1.5).

Keys stored before this change hold the body's hash alone, so a repeat of
such a call after the deploy answers `409 idempotency_mismatch` until the
key's 24 hours of retention are over. That is accepted: a key's repeat is
a retry after a lost answer, rare, and the same call with a new key works.

**Rejected alternatives:**
- A key scoped per project (the project as part of the unique key): fixes
  only the project case, not the same key on another route of the same
  project, and needs a migration of the key table.
- Checking only the authorization again at the replay: the caller may be
  allowed in both projects, and still gets the wrong project's resource.
- The raw request path in the hash: an old name of the project, which
  still resolves, would turn a retry after a rename into a mismatch.

## A replay passes the same read as a fresh request, before anything is loaded

**Id:** 3f8b1c80-d1f3-49fc-be29-16f4f076bf28
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-cjafxd0mchhh (authorization hardening), 2026-11-13
**Revisit when:** a resource type is added to `idempotency.LOADERS`, or a replay is meant to answer someone who no longer reads the resource
**See:** idempotency.md#a-key-replays-only-the-call-it-was-first-used-for-method-route-resource-and-body — be28183d-90cd-4acd-b043-59819643f89d — as of 2026-11-13

A replay answers with the resource as it is now, not with a stored
response. So it re-checks access first: every resource type is registered
with `idempotency.register(type, loader, may_see)`, and `_replay` asks
`may_see(conn, id, caller)` before the loader runs. Where it says no, the
answer is `not_found`, as the caller's GET would be. For a project's
resources, `in_project` checks the active membership with `project:read`,
plus the rule the resource's own GET adds (the invitation and join lists,
a credential's managers, a request's readers, a group chat's messages, an
attachment's readers, the webhook's admins, an agent's own placements,
the readers of a jour fixe round or series). Outside projects, the check
is the GET's rule as well: an agent's owner, the runner and the people who
see it, a cross-owner chat's readers. A human's own records (`/me`, their
preferences and chat-access lists, their reports) need no further look,
since the key is theirs. One's own membership stays visible after a
leave, so the leave's retry still replays. Where a route lets someone act
on what its GET does not show them, the check admits them too, for the
final state their action left: a bridge agent's owner from outside the
project ending the connection, an owner of either side or an admin
withdrawing a pair's request, someone added to a group chat later
redacting an earlier message it reads in the history.
`tests/test_replay_access.py`
names every registered type, so a new loader fails it until someone
decides what its replay may show.

**Reason:** before this, `_replay` ran before the route's action, where
the checks live, and several loaders built the view without looking at
the caller. A loader that looks for itself is one forgotten check away
from the same gap. Registering the check next to the loader makes it a
required argument, and the test makes a new type a deliberate choice.

**Rejected alternatives:**
- Running the route's authorization before `_replay`: the checks sit
  inside each action, mixed with the write and taken under its locks, so
  they cannot be run apart from it without splitting every route. A
  write's check is also stricter than a read's: someone who may still
  read the resource, but no longer change it, would lose the answer to
  their own earlier call.
- Dropping a member's stored keys when the membership ends: access is
  also lost in other ways (a role or scope change, leaving a chat, a
  restricted set), so it would not be enough on its own.
- Patching only the loaders found without a check: it leaves the next
  loader to whoever adds it, with nothing that fails.
- Admitting the member who forwarded an owners' round request on: the
  request stays open, so the replay would show what the next holder does
  with it, which the round keeps from them. Their retry gets `not_found`.
