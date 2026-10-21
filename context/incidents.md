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
