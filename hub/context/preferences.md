# Preferences

## A preference proposal's go is checked before it is answered, and the human's edit travels in the proposal

**Id:** 3f1e2f4e-5cca-4b98-9df5-51c874f84bbd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-23 (preferences, §19.4)
**Revisit when:** proposal settlements get the answer's body, or another kind needs to refuse an answer by its content

The personal answer route asks `preferences.check_answer` first: a `go`
on a stale `base_version`, plain or edited, is `conflict` and the request
stays open. An edited `go` writes its `markdown` and `base_version` into
the request's `proposal` as `edit`, in the same transaction, before the
request is marked answered; the registered settlement then applies the
proposal as stored, and records `result: {version, edited}` there too.

**Reason:** the proposals registry settles a request from the request
row alone (`proposals.Settlement` carries no answer body), after the
answer is stored. A conflict found there would come after the request was
already answered, and the human's edit would not reach it. Checking first
keeps a stale go from closing the request; carrying the edit in the
proposal keeps one settlement path for every proposal kind.

**Rejected alternatives:**
- Pass the answer body into `Settlement`: a change to every kind's
  signature for one kind's need.
- Apply preferences in the answer route itself, outside the registry: a
  second path for proposals, which the registry exists to avoid.
