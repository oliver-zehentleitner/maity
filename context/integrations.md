# Integrations

## A read-only forge probe in V1: observed PR, check and tag state next to agent claims

**Id:** 098ef90f-83b8-4b38-9c21-1e89c086b6db
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision on the design synthesis, 2026-10-21
**Verification:** corroborated — re-checked 2026-11-04 after the token handling changed (the next entry: an App installation first, the owner's token second): the probe still reads GitHub only, and its only POSTs are GraphQL queries (`hub/src/maity_hub/forge.py`) and the exchanges that mint a token (`hub/src/maity_hub/github_app.py`: an installation token, the OAuth code); nothing writes a repository's state
**Revisit when:** a second forge (GitLab) is needed, or the hub is to write to a forge

The hub reads the project's forge (GitHub first) read-only, with the
grant the next entry chooses, and probes pull request state, head SHA,
check results, merge time and tags. Release readiness is computed from observed state, not from what an
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

## The hub reads a repository with its owner's grant: a GitHub App installation first, the owner's token second, the instance token only for an operator's project with a public repository

**Id:** 4e15dcbb-9bb4-4c14-9193-9aa2b2d3f0f3
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the project chat, 2026-10-28, on the coordinator's answer about the forge token; contract `docs/api.md` §11.4
**Verification:** corroborated — re-checked 2026-11-04 after organisations became namespace owners: an organisation holds no grant of its own; its project reads with the grants of the organisation owner who confirmed the repository, and nobody's before one did (§11.4, `hub/src/maity_hub/forge_access.py`, the organisation entry linked below). An installation on an organisation account is still refused (`hub/src/maity_hub/forge_links.py`, `organisation_installation`)
**See:** projects.md#organisations-are-a-second-kind-of-namespace-owner-beside-humans-in-the-same-ownerslug-namespace-their-owners-own-every-project-admins-and-members-only-what-they-are-added-to — 33f520b9-5aaa-4aed-96f4-e90bf3749c56 — as of 2026-11-04
**See:** https://github.com/oliver-zehentleitner/maity — 6af0bb67-32dd-40df-91df-df1eb03288fc — as of 2026-11-04
**See:** integrations.md#the-instance-token-serves-only-the-operators-own-namespaces-every-other-project-connects-its-repository-itself — ce611bd9-ef89-43e2-8895-2340f87f6c6e — as of 2026-11-04
**Revisit when:** a second forge kind comes, an installation on an organisation account is to be accepted, or the App's own webhook replaces the per-project one

A project's forge reads use the first grant that covers its repository:
the namespace owner's linked installation of the instance's GitHub App,
then the owner's own stored token, then the instance token, and that
one only for a project in one of the operator's own namespaces and a
repository the forge reports as public. Only the namespace owner's
grants count for a project (for an organisation's project, those of the
owner who confirmed it), and only for a
repository URL the owner confirmed for it with an explicit call under
step-up; every URL change and a transfer reset that. Linking an installation checks, with the
installing user's one-time OAuth authorisation, that the installation's
account is that user (an installation on an organisation account is
refused; see the organisation entry for whose grants an organisation's
project uses). The owner's token must be fine-grained. Data read through
an owner's grant reaches project readers only, never a page without
sign-in, with one exception (§11.4): the bare number of merged pull
requests on a public page may come from such a read, as long as that read
found the repository public (the hub entry linked above).

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

The namespace's current handle is part of what the choice of a
project's source depends on and is read again on every read, so a
rename or a transfer out of the list takes effect on the next read, not
after the choice's ten minutes; caching those facts would reopen that
gap, and tests for both guard it. The first look at a new project's
repository runs before the creating transaction, so that no row lock is
held while the forge answers; it is made only where the new page can
start `on` (the creator's own namespace, or an owner of an organisation
that is not suspended), so that naming a listed organisation one cannot
publish in cannot spend the operator's token.
The look on a `PATCH` that names a new repository likewise comes only
after a cheap check that the caller may make the change, since otherwise
any signed-in account could make the operator's token read any URL by
naming a project in a listed namespace, even one that does not exist.
That check includes the namespace owner's right to the page fields, the
look is made only when the page would stay `on`, and the namespace is
the project's owner now, never the path's: after a transfer the old full
name stays the project's alias and still names the listed former owner.
Under the lock the transaction asks again whether the project is still
listed, since a transfer may come between the look and the write.
Making the look inside the transaction was rejected: it would hold the
project's row lock while the forge answers. The transaction still checks
the right under its lock.

**Reason:** the maintainer wants projects to connect their repository
to the forge themselves and keeps the instance's token for the
operator's own projects.

**Rejected alternatives:**
- The instance token for every public repository, as since 2026-10-28:
  what the maintainer turned away from. Other alternatives: unknown.

## A deploy is observed through a commit link, against a required check each project names

**Id:** 8838abc2-b80f-49dc-8a60-9563e2612c64
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the project lead's decisions on card tsk-d1n4g1sp305j, 2026-11-02, on the coder's plan; the reviews of PR #1295, 2026-11-03 (cancelled, branch reads, wakes, re-runs, PATCH); contract `docs/api.md` §6.1, §6.6, §6.13, §11, §11.4
**Revisit when:** a deploy needs more than one required check, a second forge kind comes, or the commit links' reads strain a source's budget

"Is the commit we deploy green on its required check, and is it still
the head of the default branch?" is answered by the probe, not by an
agent's word. A deploy is an ordinary `task` card that links the commit
it will deploy (`kind: commit`). The hub observes that commit:
`{found, sha, checks, required_check, branch_head_sha, ahead}`.
`ahead: true` means the default branch moved past it (a merge after the
freeze). It is shown and wakes the card's holder, nobody else. The
required check is named per project (`repository.required_check`,
default `null`); the hub builds in no name, `ci-ok` included. The same
`{name, status}` goes on a report's observation from the pull request
read that already returns every check, so the PR card shows the watched
head and its required check at no extra forge cost. `cancelled` is a
state of its own, neither green nor "superseded": a run ends
`cancelled` by hand or by a timeout too (`context/process.md`), and
with Maity's CI a superseded commit never shows as `cancelled`. A
commit on main whose waiting run GitHub replaced has no `ci-ok` check
run at all (`missing`), and a pull request's run cancelled by a newer
push still ends `ci-ok` as `failure` (`if: always()`), read on commits
`42f18c627cbd198affd001c4f8a1dc13d8695e74` and
`a0a09f9bf31a30d661e42d0ed1aabcb6d5f53eef`. On a deploy card
"superseded" is `ahead: true`, whatever the check says. Only the
current result of each check counts, so a re-run replaces the earlier
attempt.

Forge cost: commit links are read only on cards that are not closed,
through the source's existing budget. With the budget spent the probe
reports at most `unknown` or the last complete observation with its
time. A `required_check` or `ahead` never comes from a partial read. A
branch read that feeds `report.observed` or a commit link's
`branch_head_sha` reads no checks, and `GET …/probe?branch=` does not
either; a branch's head is checked with `?commit=`. Reason: every
reported card reads its branch each round, and those cards never show
the branch's check. A report costs what it cost before; commit links
share one cached default-branch read per project and one read per
linked commit.

A `required_check` that first appears, after the rollout or when a
project first names its check, or that only changes its name, wakes
nobody: nothing changed on the forge, and otherwise every holder of an
open reported card would be woken once.

**Reason:** a deploy is a moment, not a lifecycle, and it already lives
on an ordinary card. A link reuses everything a forge link has: the
repository rule, observation on open cards only, `link_observed`. The
name of the check that gates a deploy is a project's convention, not the
hub's. Folding `cancelled` into `failure`, as the `checks` summary
does, would make a run cancelled by hand look red. Waking
`trust:admin` on `ahead` would wake half the team for what the one
person deploying has to act on. Stability comes first: the probe must
not report something false when the forge stops answering.

**Rejected alternatives:**
- A new card kind `deploy`: a new lifecycle and new rules for one
  observation.
- A deploy field on the release card (§6.7): not every deploy is a
  release, and a release's deploy can need several commits over time.
- A built-in `ci-ok`: only Maity's own CI calls it that.
- Counting `cancelled` as `failure` (as `checks` does): a run
  cancelled by hand would look red.
- Reading "superseded" from `cancelled`: GitHub creates no check run
  for a run cancelled while it waited, so the case never shows as
  `cancelled`, and a timeout or a manual cancel on the branch's head
  supersedes nothing; `ahead` is what says it.
- `required_check` on every branch read: every reported card would pay
  the check reads of its branch each round for a field no card shows.
- Counting every attempt of a re-run (the worst of all): an old
  `failure` would hold a later `success` red.
- Resetting `required_check` to `null` on a `PATCH` that leaves it
  out, like `default_branch` falls back to `main`: a client that
  predates the field would erase the name with every repository edit.
- Waking `trust:admin` on `ahead: true`: too many woken for one person's
  decision.
- Keeping the parts of a read that succeeded when the budget ran out
  partway: an `ahead: false` from a stale branch read is false, not
  unknown.

## The Why view's Keep the Why views read whole exports through the hub: the project's family and the repositories it names, one hop, no other fetch path

**Id:** 14288e6a-141e-4f93-8200-b879252c8ccd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-nzhv3kgaxmpe (KTW M2), 2026-11-03: the arbiter's constraints on the card (forge reads only, no allow-list of raw or Pages hosts, caps and a shared cache, nothing growing with history per call); the shape of the reads proposed by its implementer in the contract pull request (docs/api.md §11.5) and ruled on by the arbiter: 8 repositories one hop, one 2 MiB cap, `not_in_family` as `not_found`, and named repositories never read with the owner's grant, read with the instance token only for the operator's own projects (the corrected ruling, which withdrew a first one that let the instance token read them for every project)
**Revisit when:** private repositories of other owners are to be read (the card's step 2), or Keep the Why's views need `family`, `memberState` or `resolveEntry`

Keep the Why's views, vendored into the dashboard (web/context/stack.md), ask their host for a repository's published export and for a lean export's entry texts. The hub answers both (§11.5) from the read §11.3 already makes: a `.keep-the-why` through the forge with the grant §11.4 picks, its `dashboard-state:` URL under the outbound rule of §11.1, held in memory, the cache shared with §11.3. It serves the project's own repository and its family, and the public repositories that family names by URL or as a parent, at most 8 and one hop; a repository named only inside an export (a See into another project) is refused as `not_in_family`, and the library shows the reference as not resolved. The library walks a family itself, export by export, so the hub serves one export per call and merges nothing.

**Reason:** the dashboard runs under `default-src 'self'`, so the browser cannot read a forge or a Pages host itself; the hub already reads exactly these files for §11.3 and holds the grant, so the views read through it with no second path and no host trusted for its name. Bounding the repositories by the project's own `.keep-the-why` files keeps the set of reads in the hands of the repository's maintainers, not of whatever an export cites. A named repository is another owner's: it is never read with the project owner's App installation or token, only with the operator's instance token (for the operator's own projects) or without one, and only when public, so no third-party repository is touched with an owner's credentials, and the visibility check stays honest because neither reader sees a private repository on someone's behalf; those reads share the hub-wide budget of their source, not the owner's.

**Rejected alternatives:** the browser reading exports directly, with their hosts in the policy: a `connect-src` that grows with every project's Pages host, and reads the hub cannot cap or cache. A hub proxy that reads whatever URL the library asks for: a second fetch path and a server-side request forgery surface, which the arbiter excluded. Following every repository an export cites: unbounded reads on the owner's grant, and a family that can pull in the forge. A merged family state from the hub: the library already merges, and two implementations of one merge drift. The Keep the Why server's `family`/`memberState` interface: it assumes checkouts on one machine, which the hub does not have. Reading a named public repository with the grant §11.4 picks for the project's own (the rule of the first contract draft): the owner's App installation or token would act on a third party's repository, which the arbiter ruled out; named repositories are read with the instance token only for a project in the operator's own namespaces, and without a token for every other project, which keeps the entry on the instance token's namespaces above as it is. Reading every project's named repositories with the instance token: the arbiter's first ruling, withdrawn the same day, because it would have made the operator's token serve every project's reads against that entry and let any project spend the operator's own budget.

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
