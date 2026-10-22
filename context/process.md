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
**Evidence:** confirmed
**Source:** the maintainer's statement, 2026-10-22
**Revisit when:** work on Maity needs something the hub cannot carry yet, or maity.team is down for longer than the work can wait

From 2026-10-22, the work on Maity runs through maity.team only: cards,
claims, questions to the maintainer, messages between agents and
reports. New agents join there with a join line; the maintainer talks to
them there.

**Reason:** the maintainer's: use the product to find its gaps. Dogfooding
had already found defects the fixtures hid — the install line, cards
whose result is not code, the pointer block written into a tracked file.

**Alternatives:** unknown.

## Reviewer independence assumes separate environments; two identities in one workspace mixed up credentials

**Id:** 5380a247-324f-4ab8-92c6-37350e02b0cb
**Type:** constraint
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's observation, 2026-10-22
**Revisit when:** the contract for tracking an agent's environment is decided
**See:** process.md#pull-requests-get-an-independent-first-review-on-a-different-vendors-model-the-coordinator-decides-disagreements-go-to-the-maintainer — 0b12c29d-1539-4737-9bc3-e5e5815238ec — as of 2026-10-22

Two agent identities working in one shared Codex workspace once mixed up
their credentials. An independent review only counts as independent when the reviewer runs
in an environment of its own, with its own clone and its own state
directory, so each identity stays separate from the agents it reviews.

**Reason:** a reviewer sharing an environment with the agents it reviews
can act under, or read as, another identity, which undoes the point of a
second pair of eyes. Whether and how the hub tracks an agent's
environment is an open decision with the maintainer.

**Alternatives:** unknown — open until that decision.
