# Integrations

## A read-only forge probe in V1: observed PR, check and tag state next to agent claims

**Id:** 098ef90f-83b8-4b38-9c21-1e89c086b6db
**Type:** decision
**Status:** needs-review
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
**Status:** needs-review
**Evidence:** confirmed
**Source:** the maintainer's decision in the project chat, 2026-10-28, on the coordinator's answer about the forge token; contract `docs/api.md` §11.4
**Revisit when:** a second forge kind comes, organisations become namespace owners (§6.25), or the App's own webhook replaces the per-project one

A project's forge reads use the first grant that covers its repository:
the namespace owner's linked installation of the instance's GitHub App,
then the owner's own stored token, then the instance token, and that
one only for a repository the forge reports as public. Only the
namespace owner's grants count for a project, and only for a
repository URL the owner confirmed for it with an explicit call under
step-up; every URL change and a transfer reset that. Linking an installation checks, with the
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

## The instance token serves only the operator's own namespaces; every other project connects its repository itself

**Id:** ce611bd9-ef89-43e2-8895-2340f87f6c6e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer to req-d8n8j0t2gv9j, 2026-11-02 ("ich will das projekte ihre projekt selber mit github verschränken. unsere key heben wir für usnere projekte auf."); card tsk-frfcjf7q1mja; contract `docs/api.md` §11.4
**Revisit when:** the operator wants to offer forge reads to other projects again, or a second forge kind comes

The instance token (`MAITY_FORGE_GITHUB_TOKEN`) reads only for projects
in the namespaces the operator lists (`MAITY_FORGE_INSTANCE_NAMESPACES`),
and there still only public repositories. Every other project is read
only through its namespace owner's App installation or own token, after
the owner confirmed the repository; without one it has no forge access
at all, not even the visibility check, and the dashboard asks the owner
to connect. Unset, the token serves no project. This narrows the third
source of the entry above (4e15dcbb), which stands otherwise.

**Reason:** the maintainer wants projects to connect their repository
to the forge themselves and keeps the instance's token for the
operator's own projects.

**Rejected alternatives:**
- The instance token for every public repository, as since 2026-10-28:
  what the maintainer turned away from. Other alternatives: unknown.

## A listed namespace name nobody has is held for the operator; an alias and the operator's own command are not

**Id:** d74e201f-7f31-4a5e-8482-2c3d91b30353
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the project lead's decisions on the review of the contract (`docs/api.md` §11.4), 2026-11-02: the hold as a must, the exception for `maity-hub owner create`; the alias exception from the same review; card tsk-frfcjf7q1mja
**Revisit when:** the instance token's namespaces are configured anywhere but the server's environment, or names can be released

A name in `MAITY_FORGE_INSTANCE_NAMESPACES` that is neither the handle
nor an alias of any human or organisation is `reserved` while it is
listed: registration, `POST /orgs` and every rename refuse it, and the
hub warns at start about it and about a listed name that is only an
alias. `maity-hub owner create` may take it, and an alias stays with
its id, which may take it back.

**Reason:** the instance token reads for whatever namespace carries a
listed name (ce611bd9). A typing error in the list, or an organisation
the operator has not created yet, would otherwise let anyone register
the name later and have their projects read with the operator's token.
An alias needs no hold, since it is never another's (§6.24), and holding
it would stop the operator taking back their own former name. `owner
create` runs on the server with the hub's configuration and database,
so whoever runs it is the operator who also sets the list.

**Rejected alternatives:**
- Only a warning at start, or the risk named as the operator's duty: a
  warning in a log does not stop a registration.
- Holding every listed name that is not a current handle, aliases
  included: blocks the operator's own rename back.
- Holding the name for `owner create` too: the operator could create
  their own listed account or organisation only after taking the name
  off the list and restarting.
