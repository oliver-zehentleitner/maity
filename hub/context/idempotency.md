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
