# Integrations

## A read-only forge probe in V1: observed PR, check and tag state next to agent claims

**Id:** 098ef90f-83b8-4b38-9c21-1e89c086b6db
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on the design synthesis, 2026-10-21
**Revisit when:** a second forge (GitLab) is needed, or the probe's token handling has to change

The hub holds a read-only token for the project's forge (GitHub first)
and probes pull request state, head SHA, check results, merge time and
tags. Release readiness is computed from observed state, not from what an
agent reported; an agent-typed reference that does not match is shown as
such. The hub never writes to the forge.

**Reason:** the maintainer wants the dashboard to bring information
together, and the one class of claim that was wrong repeatedly in the
earlier experiment was exactly "merged" and "green" typed by an agent.
A small poller turns those claims into facts.

**Rejected alternative:** attestation only, with an "unverified" badge,
keeping the hub free of any forge dependency and one secret poorer — the
handover concept's position. Rejected because a release gate that trusts
descriptions repeats the incident it is meant to prevent.
