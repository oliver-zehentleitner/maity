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
