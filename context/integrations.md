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

## The hub reads a repository with its owner's grant: a GitHub App installation first, the owner's token second, the instance token for public repositories only

**Id:** 4e15dcbb-9bb4-4c14-9193-9aa2b2d3f0f3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the project chat, 2026-10-28, on the coordinator's answer about the forge token; contract `docs/api.md` §11.4
**Revisit when:** a second forge kind comes, organisations become namespace owners (§6.25), or the App's own webhook replaces the per-project one

A project's forge reads use the first grant that covers its repository:
the namespace owner's linked installation of the instance's GitHub App,
then the owner's own stored token, then the instance token, and that
one only for a repository the forge reports as public. Only the
namespace owner's grants count for a project, and only for a
repository URL the owner confirmed for it; a co-admin's change or a
transfer resets that. Linking an installation checks, with the
installing user's one-time OAuth authorisation, that the installation's
account is that user (organisation installations wait for organisation
namespaces). The owner's token must be fine-grained. Data read through
an owner's grant reaches project readers only, never a page without
sign-in.

**Reason:** one instance token cannot read the private repositories of
the people who host projects on an instance, and a token from the
operator's account would let any project read the operator's private
repositories through the probe. A GitHub App is granted by the
repository's owner per repository, read-only, with tokens that expire in
an hour; the owner can revoke it on the forge at any time. The owner's
own token is the fallback for setups where an App cannot be installed,
and the maintainer expects owners to bring their own access as the
instance grows.

**Rejected alternatives:**
- One instance token for everything, as in V1: cannot cover others'
  private repositories, and a broad one exposes the operator's.
- A token per project, set by a project admin: the project admin is not
  necessarily the repository's owner, and the same token would be
  copied into every project.
- An OAuth App acting as the user: its `repo` scope is read and write
  on every repository the user can reach, far more than the probe needs.
- Trusting the `installation_id` the forge sends back to the setup URL:
  anyone can send any id.
- Checking only that the user can access the installation (the user's
  installation list): a member of an organisation with access to one
  repository would pass and the hub would read every repository of the
  installation. The installation's account must be the user.
- Using the owner's grant for whatever URL the project names: a co-admin
  could point the project at another private repository of the owner;
  the owner confirms the URL instead.
- Accepting classic tokens: without `repo` they read only public
  repositories, and `repo` can write.
- Using any project member's grant: a member could make the hub read a
  repository with someone else's access by naming it in a project.
