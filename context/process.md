# Process

How Maity itself is built: the rules its own agents and maintainer work
by, where they differ from what the product prescribes.

## Pull requests get an independent first review on a different vendor's model; the coordinator decides, disagreements go to the maintainer

**Id:** 0b12c29d-1539-4737-9bc3-e5e5815238ec
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's statements, 2026-10-22, relayed by the coordinator
**Revisit when:** the first-pass reviewer and the coordinator disagree often enough that the maintainer becomes the bottleneck, or the review cost becomes binding again
**See:** incidents.md#multi-agent-review-runs-exhausted-the-maintainers-monthly-budget — 1a5e729f-816a-4682-ab8c-a2029aa1ea0a — as of 2026-10-22

A reviewer running on ChatGPT does the first pass on a pull request and
reports to the coordinator (the admin agent). The coordinator verifies
its findings in the code before posting them and decides; where the two
disagree, the question goes to the maintainer with both positions
written out. This extends the earlier process rather than replacing it:
where security is at stake (the runner, the hub's security slices) the
coordinator still runs its own adversarial reviews.

**Reason:** the maintainer wants the first pass to relieve the
coordinator and to question it again from another angle — a reviewer on
another vendor's model does not share the coordinator's view of the code.

**Rejected alternative:** a further admin or proxy agent between the
maintainer and the team, considered by the coordinator. Rejected because
communication was not the bottleneck, and every relay loses detail.

## Dogfooding: maity.team is the only platform for building Maity

**Id:** 9d07bc5d-a65e-46d9-809f-c80353be6319
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's statement, 2026-10-22
**Revisit when:** work on Maity needs something the hub cannot carry yet, or maity.team is down for longer than the work can wait

From 2026-10-22, the work on Maity runs through maity.team only: cards,
claims, questions to the maintainer, messages between agents and
reports. New agents join there with a join line; the maintainer talks to
them there.

**Reason:** the maintainer's decision; the stated part is only that
everything runs through Maity from now on. The inferred part: dogfooding
already found defects the fixtures had hidden (the install line, cards
whose result is not code, the pointer block written into a tracked
file), and running all of the work on the hub turns every gap into a
finding instead of something worked around elsewhere.

**Alternatives:** unknown.
