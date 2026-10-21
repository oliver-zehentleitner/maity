# Incidents of the build

What went wrong while a coordinating agent and three coding agents built
Maity together on one machine, and what each incident means for the
product: Maity exists to coordinate exactly this kind of team, so every
failure here is a requirement for its processes and tools.

## The shared machine ran out of disk; review artefacts filled it

**Id:** b1c7bd7d-a497-41ed-97e3-989f63c80a1c
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

The root filesystem of the shared VM reached 100 %. Every session
stopped writing: Git could not create an index lock, test runs failed
with ENOSPC. The space was held by review runs — dozens of reviewer and
verifier agents each created a virtual environment under `/var/tmp`,
built container images and left a build cache of 12 GB behind — next to
a finished project's images. Cleaning up needed a human: the agents'
harness refused deletions outside their own scope, rightly.

**Learned:** work that fans out must bring its own clean-up and must
check the shared resource before it starts. Reviewers now keep scratch
data on a tmpfs and delete it when done; image builds stay out of
reviews. For Maity this is a checklist item for any role that starts
parallel work, and a reason to show the hosts the agents share as
something a project knows about.

## Multi-agent review runs exhausted the maintainer's monthly budget

**Id:** 1a5e729f-816a-4682-ab8c-a2029aa1ea0a
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

Two review runs — three dimensions per pull request, an independent
verifier per finding — used several million tokens each; the day's
background agents used roughly twenty million. The second run hit the
maintainer's monthly spend limit, and 54 verifiers stopped mid-way, so
part of the findings were judged rather than reproduced. Reviews were
switched to one reviewer per pull request that reproduces its own
blocker and should-fix findings, plus a targeted re-check by the
coordinator: about 150 thousand tokens per review, and the reviews kept
finding real defects (two of them blockers in the release gate).

**Learned:** the token budget is a shared, binding constraint, as it was
in the earlier seven-agent project. Maity records the model on every
event so that cost per role and per kind of work can be compared later;
a budget the admin roles can see, and review depth as a project policy
rather than a habit, are the follow-ups.

## One agent stopped another's server: process clean-up by pattern

**Id:** 871f9226-a39d-4a71-84a6-c0b65a4fbf2e
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

An agent ended its own test server with `pkill -f "maity-hub serve"`. The
pattern also matched the dogfood hub the maintainer was about to use,
and a leftover server of an earlier review that had held port 8080 for
hours. The agent reported it at once and precisely; the hub was
restarted without data loss. The leftover had already forced the
dogfood hub onto another port.

**Learned:** on a shared machine a process belongs to whoever started
it. The rule for every agent since: start servers in the background,
keep the PID, kill exactly that PID, never by pattern, and treat the
dogfood hub's port as off limits. For Maity this belongs in the rules a
project serves to its agents, and the dogfood hub's address is project
knowledge every agent receives at join.

## The contract contradicted itself, and an implementation took one side

**Id:** a693f08e-ee64-44b7-b245-872065c2dc0e
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21; reviews of pull requests #21 and #30

Two review blockers came from the API contract, not from the code. The
PATCH rule for cards named holder, creator and admin, while the scope
table gave reviewers the right to close a reviewed card; the hub
implemented the narrower rule, so under the default organisation preset
the reviewer could never close anything. And "release groups among the
shipped cards" was implemented literally, so a paired card left out of
a release was ignored — the half-merged pair the release gate exists
for. Each implementation also listed its own readings of open points,
and most of the contract's later amendments came from those lists.

**Learned:** a written contract with one owner works only if ambiguity
surfaces before the code. The habit that worked: every slice lists the
readings it chose, the contract owner decides each in the document
before the merge, and reviews check the contract against itself as well
as the code against the contract. Maity's contract cards (one arbiter,
proposed then final) are the product form of this.
