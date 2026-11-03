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

## The Why view's Keep the Why views read whole exports through the hub: the project's family and the repositories it names, one hop, no other fetch path

**Id:** 14288e6a-141e-4f93-8200-b879252c8ccd
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** tsk-nzhv3kgaxmpe (KTW M2), 2026-11-03: the arbiter's constraints on the card (forge reads only, no allow-list of raw or Pages hosts, caps and a shared cache, nothing growing with history per call); the shape of the reads proposed by its implementer in the contract pull request (docs/api.md §11.5)
**Revisit when:** private repositories of other owners are to be read (the card's step 2), or Keep the Why's views need `family`, `memberState` or `resolveEntry`

Keep the Why's views, vendored into the dashboard (web/context/stack.md), ask their host for a repository's published export and for a lean export's entry texts. The hub answers both (§11.5) from the read §11.3 already makes: a `.keep-the-why` through the forge with the grant §11.4 picks, its `dashboard-state:` URL under the outbound rule of §11.1, held in memory, the cache shared with §11.3. It serves the project's own repository and its family, and the public repositories that family names by URL or as a parent, at most 8 and one hop; a repository named only inside an export (a See into another project) is refused as `not_in_family`, and the library shows the reference as not resolved. The library walks a family itself, export by export, so the hub serves one export per call and merges nothing.

**Reason:** the dashboard runs under `default-src 'self'`, so the browser cannot read a forge or a Pages host itself; the hub already reads exactly these files for §11.3 and holds the grant, so the views read through it with no second path and no host trusted for its name. Bounding the repositories by the project's own `.keep-the-why` files keeps the set of reads in the hands of the repository's maintainers, not of whatever an export cites, and keeps the forge budget of the owner's grant bounded per project.

**Rejected alternatives:** the browser reading exports directly, with their hosts in the policy: a `connect-src` that grows with every project's Pages host, and reads the hub cannot cap or cache. A hub proxy that reads whatever URL the library asks for: a second fetch path and a server-side request forgery surface, which the arbiter excluded. Following every repository an export cites: unbounded reads on the owner's grant, and a family that can pull in the forge. A merged family state from the hub: the library already merges, and two implementations of one merge drift. The Keep the Why server's `family`/`memberState` interface: it assumes checkouts on one machine, which the hub does not have.
