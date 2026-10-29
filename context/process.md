# Process

How Maity itself is built: the rules its own agents and maintainer work
by, where they differ from what the product prescribes.

## Pull requests get an independent first review on a different vendor's model; the coordinator decides, disagreements go to the maintainer

**Id:** 0b12c29d-1539-4737-9bc3-e5e5815238ec
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** the maintainer's statements, 2026-10-22, relayed by the coordinator
**Revisit when:** the first-pass reviewer and the coordinator disagree often enough that the maintainer becomes the bottleneck, or the review cost becomes binding again
**Verification:** contradicted — the maintainer's statement of 2026-10-27 (the coordinator is not the reviewer) contradicts the coordinator's own adversarial reviews kept here; see process.md#the-coordinating-agent-manages-merges-and-releases-it-does-not-code-review-or-test-and-it-routes-work-by-model — 11b7ed4d-100d-490f-ab34-c68ace8b5f80
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
**See:** trust.md#members-sharing-an-environment-are-warned-never-refused — abd84bd0-a085-4d5a-b3b0-f8358c12e444 — as of 2026-10-22
**See:** process.md#pull-requests-get-an-independent-first-review-on-a-different-vendors-model-the-coordinator-decides-disagreements-go-to-the-maintainer — 0b12c29d-1539-4737-9bc3-e5e5815238ec — as of 2026-10-22

Two agent identities working in one shared Codex workspace once mixed up
their credentials. An independent review only counts as independent when the reviewer runs
in an environment of its own, with its own clone and its own state
directory, so each identity stays separate from the agents it reviews.

**Reason:** a reviewer sharing an environment with the agents it reviews
can act under, or read as, another identity, which undoes the point of a
second pair of eyes. Whether and how the hub tracks an agent's
environment is decided: the hub warns, not refuses, when environments are
shared; the coordinator acts on the warning (re-confirmed by the
coordinator, 2026-10-22).

**Alternatives:** unknown.

## Changelog entries are one file per pull request in changelog.d/, folded into CHANGELOG.md at release

**Id:** b1258d90-a82b-48a1-9c5f-7ee4eb1295f9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-22, via the inbox
**Revisit when:** GitHub runs checks on pull requests with merge conflicts, or the team shrinks to one pull request open at a time

A pull request adds its changelog entry as a new file in `changelog.d/`
and never edits `CHANGELOG.md`; `tools/changelog.py release` folds the
files into a version section of `CHANGELOG.md` (Keep a Changelog format
unchanged) and deletes them. CI validates the files. The format is in
`changelog.d/README.md`.

**Reason:** every pull request added lines under `[Unreleased]` in the one
file, so each merge put nearly every other open pull request into
conflict, and GitHub runs no CI on a pull request with conflicts — agents
spent rounds rebasing only to get their checks to run. Separate files
cannot conflict.

**Rejected alternative:** `merge=union` for `CHANGELOG.md` in
`.gitattributes`. Not relied on: whether GitHub's server-side merge and
its conflict check honour merge attributes could not be confirmed (the
reports found say it did not), and a union merge would place
concurrent lines without regard to the headings they belong under.

**Rejected alternative:** keeping the single file and rebasing on every
merge — the status quo that caused the problem.

## Overnight, the coordinator deploys maity.team without a per-deploy go once main is green

**Id:** 3ac98e12-f84b-423d-98de-3d3f7f610b8f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's standing instruction, 2026-10-22, relayed by the coordinator
**Revisit when:** the maintainer withdraws the standing instruction, or a deploy without a go breaks maity.team
**See:** https://github.com/oliver-zehentleitner/maity — 5e42eb26-9883-49e2-89c0-9fe4e6517c62 — as of 2026-10-22

For the night of 2026-10-22 the maintainer gave a standing instruction:
the coordinator deploys a new image to maity.team before the maintainer
is back, once `main` is green after the merges, with no go per deploy.
The rollout follows one sequence: the image from the publish workflow on
`main`, its digest pinned in the Helm values, a database dump from the
backup job first, `helm upgrade --wait`, migrations on start, then
`/api/v1/health` checked for the schema head and the dashboard opened.
The few seconds of 503 during the rollout are expected and accepted, not
an incident: the hub runs as one pod replaced with `Recreate`, for the
reasons in the hub's Kubernetes entry.

**Reason:** the maintainer's instruction; no reason beyond having the
night's merges deployed before the maintainer is back was stated.

**Alternatives:** none were weighed.

## When a reviewer returns, the cover's finished reviews stand and the returning reviewer takes the unstarted ones

**Id:** 8ba32bfa-41ff-4351-8884-4ac5ee08bae5
**Type:** decision
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's rule, 2026-10-22, set when the reviewer came back from a usage limit
**Revisit when:** a second reviewer joins, or reviews are reassigned in a way the board can show without a list from the coordinator
**See:** process.md#pull-requests-get-an-independent-first-review-on-a-different-vendors-model-the-coordinator-decides-disagreements-go-to-the-maintainer — 0b12c29d-1539-4737-9bc3-e5e5815238ec — as of 2026-10-22

While the reviewer was stopped by a usage limit, the coordinator covered
its reviews. When the reviewer came back it asked for an exact split, so
that nothing would be reviewed twice. The rule: reviews the cover has
finished stand; every review not yet started goes to the returning
reviewer, in the order the coordinator gives, and the reviewer claims
each card before starting it.

**Reason:** the split keeps finished work and gives the review load back
to the reviewer.

**Rejected alternatives:**
- Everything back to the returning reviewer: the cover's finished
  reviews would be done again.
- The cover keeps everything it was covering: the coordinator is the
  cover, and would stay the bottleneck for reviews.

**Incident:** about two hours later the coordinator started reviews of
its own on pull requests it had already handed back, and stopped them
when it noticed. Learned: check the handback list before assigning a
review.

## A pull request runs only the suites its changes can affect; main still runs everything

**Id:** 06b11a79-65dc-4364-b6ca-bd36927ae829
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card of 2026-10-23 (the Actions queue held 30–100 runs with about seven running, and every merge waited hours); `.github/workflows/ci.yml`
**Revisit when:** a suite starts depending on files outside the paths that gate it, or a regression reaches main that a skipped suite would have caught

A first `changes` job compares a pull request's merge commit with the
base it merges into (`git diff HEAD^1 HEAD`) and gates each suite on the
paths it reads: the hub's suites on `hub/` and `docs/join-page.md` (the
join page ships in the wheel), the image also on `deploy/Dockerfile*`,
the join smoke and the browser test also on `cli/`, the dashboard on
`web/`, the CLI on `cli/`, the Helm chart on `deploy/`. The changelog
check always runs; a change to the workflow runs everything; a push to
main runs everything. A new push to a pull request cancels its older run.
`ci-ok` is the one check to require: green when every suite passed or
was not needed.

**Reason:** documentation and context pull requests ran the three
database suites, the browser test, the image and the Helm cluster, and
filled the queue that every merge waits for. Main's full run on every
merge keeps the cost of a missed path to one red main, which the next
run names.

**Rejected alternatives:**
- A third-party paths-filter action: one more pinned dependency with the
  repository's token, for a `git diff` and a `case` the workflow can
  hold itself.
- Cancelling runs on main as well: each merge's own result is the
  record a deploy is decided on.

## Every agent uses Keep the Why: implementers record each decision in the same pull request, reviewers gate on it

**Id:** e534e9f3-a419-4a09-8054-117150592490
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's rule and reason, 2026-10-25, relayed by the coordinator
**Revisit when:** the hub enforces the why reference on code reports — then this team rule gives way to the hub's policy

Every agent building Maity works with Keep the Why. An implementer
writes a `context/` entry for each decision a pull request makes, in
that same pull request, with `ktw-lint` clean (one commit per entry
until 2026-10-27, see the entry on squash merges below). A reviewer
approves only after a Keep the Why gate: the entry is there and the
linter is clean. An agent that writes
neither code nor reviews — one that rules on a question, for instance —
has its rulings recorded by the implementer of the change they decide,
not in a pull request of its own.

**Reason:** Keep the Why is part of the project, so every agent building
it uses it. The team rule is the interim: it holds until the hub
guarantees the same as a system.

**Alternatives:**
- The hub enforces it — a why reference required on code reports, set
  by policy per project. Chosen as the follow-up, not instead: its
  contract is still a proposal with the maintainer, and until it is
  built the rule and the review gate carry it.

## The CLI is published to PyPI as `maity` from a `cli-v*` tag, through trusted publishing

**Id:** 227cd75c-bfc7-4cd8-9ba8-cf877cd3bf21
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-27 (install agents the official way so that path gets used and matures); `.github/workflows/release-cli.yml`
**Revisit when:** the CLI and the hub start sharing one version, or PyPI's trusted publishing stops covering this repository's workflow
**See:** join.md#the-install-line-is-one-instance-setting-maity_cli_install-installing-from-git-until-the-package-is-on-pypi — 001ad88d-5119-4347-b0d7-72f99ec3affd — as of 2026-10-27

The agent CLI goes to PyPI under the name `maity`, the name its
command already has. A tag `cli-v<version>` starts the release; the
workflow refuses to build unless the tag, `cli/pyproject.toml` and
`__version__` name the same version, runs the CLI's checks, builds
and checks sdist and wheel, and uploads them from a job that proves its
identity to PyPI with a short-lived token. Versions start as
pre-releases (`0.1.0a1`) while Maity is before its beta.

**Reason:** agents on fresh machines could not install the CLI without
the Git URL, and the maintainer wants agents on the official path so it
is exercised. The CLI versions apart from the hub, so it gets a tag
prefix of its own beside the hub's `v*`. Trusted publishing keeps a
long-lived PyPI token out of the repository's secrets.

**Rejected alternatives:**
- Installing from the Git URL for good: works, but nobody tests the
  path most users would take.
- An API token stored as a repository secret: a long-lived credential
  that can leak; trusted publishing needs none.
- Publishing on the hub's `v*` tags: CLI and hub do not release
  together.

## The coordinating agent manages, merges and releases; it does not code, review or test, and it routes work by model

**Id:** 11b7ed4d-100d-490f-ab34-c68ace8b5f80
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's statements in the Maity chat, 2026-10-27
**Revisit when:** the hub's role briefs carry this as Maity's default (then this team rule points there); or the review agents are unavailable often enough that merges stall
**See:** process.md#pull-requests-get-an-independent-first-review-on-a-different-vendors-model-the-coordinator-decides-disagreements-go-to-the-maintainer — 0b12c29d-1539-4737-9bc3-e5e5815238ec — as of 2026-10-27

The coordinator (the admin agent) acts as the maintainer's deputy. It
routes cards, writes the contract and `context/` changes that go with
its rulings, asks the maintainer for decisions, merges once the first
pass and the final review approved the exact head and CI is green, and
releases. It does not write product code. It is not the reviewer or the
tester: reviews go to the review agents, tests to the implementers and
CI. Anything non-destructive is within its remit. It routes work by fit,
the model included: the strongest model for security-, contract- and
migration-heavy work, a faster one for well-cut UI and CLI cards. The
maintainer wants this role split to become Maity's default, carried in
every project's briefing (card tsk-2y01dmv0b0xh).

**Reason:** the maintainer wants one deputy that keeps the whole picture
and delegates, not an agent that is also busy implementing or checking
its own decisions. The roles exist in Maity to express exactly this
split.

**Rejected alternatives:**
- The coordinator reviews, itself or through its own review subagents,
  as it did until then, including the adversarial reviews on security
  work that the earlier entry kept. Its review would no longer be
  independent of its own rulings.
- The coordinator implements small items itself. That is faster in the
  moment, but it blurs who answers for the code.

## While the shared Claude budget runs low, the Claude agents work one at a time

**Id:** 31b7d6b3-054c-411d-8f2c-372831b0c773
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** the coordinator's notices of 2026-10-23 and 2026-10-24, passing on the maintainer's heads-up that the Claude agents would hit their usage limit
**Revisit when:** the usage limit has reset, or the budget stops being shared by the Claude agents
**See:** incidents.md#multi-agent-review-runs-exhausted-the-maintainers-monthly-budget — 1a5e729f-816a-4682-ab8c-a2029aa1ea0a — as of 2026-10-27

**Revisit:** the condition triggered on 2026-10-27: a new team runs on new
subscriptions, several Claude agents in parallel, on the maintainer's
instruction (coordinator, 2026-10-27). This is not today's rule; the entry
stays as the record of the earlier stretch until a person re-checks it.

When the maintainer announced that the Claude-based agents would soon
hit their usage limit, the coordinator set a working mode for the
stretch until the reset. First, every agent pushes work in progress to
its branch (without opening a pull request that is not ready), puts a
checkpoint on its card (done, next, branch, head) and leaves nothing
half-way that would break main or an open pull request. Then only one
Claude agent works at a time, in an order the coordinator names (the
roles that had open work in flight first); the others finish their
step, report and pause their wait loop until they are named. The agents
on the other vendor's model (the reviewers and the worker) keep going,
finish the reviews they hold and send patches to the coordinator
instead of merging or pushing. The remaining share was stated twice: about 4 % of the
weekly budget for about 36 hours, later about 3 % for about 22 hours.

**Reason:** the Claude agents draw on one shared budget, and parallel
work would have used the small remainder in a few hours and left several
branches half-done.

**Alternatives:** none were weighed.

## A migration chains on main's head at merge time; the numbers are reservations, and the coordinator sets the merge order

**Id:** 65a9b523-fa1f-4f1f-966c-4f49a2660343
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's notices of 2026-10-23 and 2026-10-25
**Revisit when:** parallel migration branches stop being a routine problem, or the hub gets a check that finds a diverging head before merge

Several open hub pull requests each carried a migration, numbered in
advance (0021 to 0027 at first). The rule: a pull request's migration
has `down_revision` equal to main's alembic head at the moment it merges;
the numbers are reservations, not an order. When a pull request ahead
of yours lands, you rebase and re-point `down_revision`; the
coordinator checks the chain before every merge. Later, with five
branches waiting on the same head, the coordinator gave an explicit
merge order: each owner re-points only after the coordinator's ping,
each step merges only after the previous one is on main, and branches
without an agreed place follow in the order they are reviewed.

**Reason:** the stated aim was to stop five branches racing for the
same head.

**Alternatives:** none were weighed.

## Context entries need no commit of their own; pull requests stay squash-merged

**Id:** 70b1f348-5885-4b97-95c9-70544e5ee62c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision in the Maity inbox, 2026-10-27, on the coordinator's question
**See:** process.md#every-agent-uses-keep-the-why-implementers-record-each-decision-in-the-same-pull-request-reviewers-gate-on-it — e534e9f3-a419-4a09-8054-117150592490 — as of 2026-10-27

A `context/` entry goes into the pull request of the change it explains.
It no longer needs a commit of its own, and pull requests stay
squash-merged, so on `main` an entry's time is the merge.

**Reason:** the own-commit rule existed so that an entry's Git timestamp
would record when the reasoning was written. Squash merges fold every
commit of a pull request into one, so that timestamp never reached
`main`. The rule cost each implementer extra commits and history
rewrites without serving its purpose.

**Rejected alternatives:**
- Rebase-merging pull requests that carry `context/` entries, so that
  each entry's commit and timestamp survive: recommended by the
  coordinator, not chosen. It lengthens the history and mixes two merge
  methods.
- Keeping the rule as it was: work without effect.

## A model change mid-session is reported at once, as a new session, so that work stays routed by model

**Id:** 210cc47e-74b9-4928-a0c6-bdf8d1ea82d1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer in the Maity chat, 2026-10-27: an agent that changes its model in the session must report it, because the hub and the team lead must know it for handing out the work; the mechanism (a resume with the new model, the `session_model_changed` event) is the coordinator's contract change (`docs/api.md` §5.3)
**Revisit when:** harnesses report a model switch to the hub on their own, or work stops being routed by model
**See:** process.md#the-coordinating-agent-manages-merges-and-releases-it-does-not-code-review-or-test-and-it-routes-work-by-model — 11b7ed4d-100d-490f-ab34-c68ace8b5f80 — as of 2026-10-27

An agent whose model changes resumes at once with the new one: the
resume opens a new session with the new `model` and keeps the claims.
When the model or harness differs from the instance's previous
session, the hub tells the agent's lead (woken) and the admins and the
agent's owner (not woken), so the lead can re-route a card the new
model should not hold. Rule 14 of the agent skill says so.

**Reason:** security, contract and migration cards go to the strongest
model and well-cut cards to a faster one; a session that silently runs
on another model than the one the hub knows breaks that routing, and
nobody can see it.

**Rejected alternatives:**
- A separate call to change the model of the open session: a resume
  already opens a session with the given model and keeps the claims,
  so a second way would only add a code path.
- Leaving it to the agent to tell its lead in a message: the hub would
  still show the old model, and every lead would have to read it.

## The site's sitemap and robots.txt are made at deploy from the pages, not kept in the repository

**Id:** 7e78b0e4-e8b4-4ce2-9a83-f9457153cd5b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card for the maintainer's need (the Google Search Console wants a sitemap), 2026-10-28; how it is made is the implementer's
**Revisit when:** the site grows pages that are not `.html` files, or a page should be left out of search results that is not under `brand/` or the dashboard

The pages workflow assembles `site/` from `docs/`, the brand files and the Keep the Why
dashboard. A last step (`tools/site_sitemap.py`) lists every `.html` file under `site/` as an
absolute `https://maity.dev/…` URL (a folder's `index.html` is the folder's address), with the
date of the last commit that touched its source as `lastmod`, and writes `sitemap.xml` and a
`robots.txt` that allows everything and names the sitemap. The dashboard is left out, since
it is generated and holds a page for every entry, and so is `brand/`, whose `.html` file is an
SVG fragment the web app inlines and no page.

**Reason:** a file kept in `docs/` would go stale with the first page added, and the workflow
already knows what it deploys.

**Rejected alternatives:**
- A `sitemap.xml` committed to `docs/`: it lists pages by hand and drifts.
- Listing every `.html` file as the card first said: it would put the brand's loader fragment
  into the sitemap.

## The database CI jobs may run on the maintainer's machine; a fork's code reaches it only through an approval

**Id:** 405c762c-11a2-4a95-a23b-0b2657a7aa8d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go and the coordinator's brief (2026-10-28); the coordinator approved the plan; the security review of the pull request (2026-10-28) corrected the first version of this entry
**Revisit when:** the repository stops being public, a job needs a secret of the repository, or hosted runners get as fast as the machine

`ci.yml` lets `hub-sqlite`, `hub-postgresql` and `hub-mariadb` run on a self-hosted runner
when the repository variable `HUB_RUNNER_LABEL` holds a label prefix (one runner service per job type, see below); unset, they run on GitHub's
runners. The runner is a user of its own with rootless Docker, no read access to anything
else on the machine and a firewall rule against local and internal services (IPv4 and
IPv6); the runner's files, hook and unit are root-owned under /opt and a system unit, not in
the runner user's home, where a job could replace them. It is not ephemeral, and a
job-completed hook tidies containers, images, volumes and the workspace.
Install steps and the trust boundary: `deploy/runner/README.md`.

The condition in `ci.yml` that sends fork pull requests to the hosted runners (since the entry "Only a push to main goes to the rented runner", every pull request) is **not** a
protection: a fork's pull request runs the fork's own `ci.yml` and can name the runner
itself. The protection is the repository setting that requires approval for every outside
collaborator's workflow run, and the rule to read `.github/` in the diff before approving.
"Only code of this repository" means every branch of anyone with push access, agents
included. After a malicious job the machine is reinstalled; the hook is housekeeping.

**Reason:** the database jobs are the long ones and the machine has more cores than a hosted
runner; with the suite in parallel they use all of them. The repository is public, so a
runner that runs fork code next to the project's credentials is the risk; the dedicated
user, the approval rule and the absence of any secret on the machine bound it. Deleting one
variable is the fallback.

**Rejected alternatives:**
- An ephemeral runner (a fresh registration per job): cleaner, but it needs a
  repository-admin token on the machine to register again, the one secret the machine must
  not hold.
- The runner under the account of the agents that work on the machine: that account can
  reach the production cluster and the maintainer's tokens.
- Docker through the docker group: the `services:` of the jobs need a Docker API, and that
  group is root on the machine; rootless Docker gives the API without it.
- Relying on the `runs-on` condition against forks: the fork controls the workflow file.
- Running every job on the machine: it runs one job at a time (the services bind host ports);
  the short jobs gain nothing there.

## The runner gets its Python through uv into the tool cache, and starts through `runsvc.sh`

**Id:** 2bede3db-2d8e-4716-851b-0ecc07cb140d
**Type:** decision
**Type:** workaround
**Status:** active
**Evidence:** confirmed
**Source:** the first installation of the self-hosted runner, 2026-10-28 (the service exited at once; setup-python found no Python 3.12; pip refused to install); the review of the installer script
**Revisit when:** setup-python supports Debian, or the database jobs run in a virtual environment on both runner kinds
**See:** process.md#the-database-ci-jobs-may-run-on-the-maintainers-machine-a-forks-code-reaches-it-only-through-an-approval — 405c762c-11a2-4a95-a23b-0b2657a7aa8d — as of 2026-10-28

The unit starts `bin/runsvc.sh`, not `run.sh`: `run.sh` copies a helper into its own directory on every start, which
a root-owned runner directory refuses, and the service then exits with status 0 and restarts in a loop.
`install-python.sh` gives the machine a Python that `setup-python` finds: uv installs 3.12 as the runner user and it is
linked into the runner's tool cache (`_work/_tool/Python/<version>/x64`); uv's PEP 668 "externally managed" marker is
removed from that private copy, because `pip install` in the jobs fails with it; the `.path` the runner stored at
registration (the PATH of root's shell, with directories the runner user may not enter) is replaced by a plain one.
Everything inside the runner user's own paths is done as that user: a job can leave symlinks there, and root following one
would write wherever it points.

**Reason:** `setup-python` knows Ubuntu, macOS and Windows; on Debian it fails with "version 3.12 not found". The tool cache
is the place it looks first, so the workflow stays the same on hosted and on the self-hosted runner. The marker is removed
only from a copy that belongs to the runner, so no system Python is changed.

**Rejected alternatives:**
- The database jobs install into a virtual environment (`python -m venv`): the same on both runner kinds and it leaves the
  runner's Python untouched, but it changes three jobs and every `make` call; the marker route is documented instead and
  this stays the revisit.
- The system Python of the machine: Debian 13 ships 3.13, the hub is tested on 3.12.
- `pip install --break-system-packages` in the jobs: it would leak a self-hosted special case into the shared workflow.
- Root creating the links and files in the tool cache: the first version did, and the review showed it follows symlinks a
  job may have left there.

## One runner service per database job type, a label each, three workers per job

**Id:** c2713d54-e602-42a3-8636-693ff3fd2c0b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the first measurements on the self-hosted runner, 2026-10-28 (one Postgres job 11 min 57 s on the machine against about 22 on a hosted runner; nine CI runs queued behind the single runner); the coordinator's go and conditions
**Revisit when:** the machine's memory or cores change, or hosted runners get as fast as it
**See:** process.md#the-database-ci-jobs-may-run-on-the-maintainers-machine-a-forks-code-reaches-it-only-through-an-approval — 405c762c-11a2-4a95-a23b-0b2657a7aa8d — as of 2026-10-28

The three database jobs run on three runner services of the machine, `maity-runner@sqlite`, `@pg` and `@maria`, each in
its own directory with its own registration and the label `<prefix>-<type>`. `ci.yml` asks each job for its own label
through the repository variable `HUB_RUNNER_LABEL` (the prefix); unset, and for every pull request (all of them since the entry "Only a push to main goes to the rented runner"), the jobs run hosted. Each service
sets `PYTEST_ARGS=-n 2` (it was `-n 3` at first, nine workers on eight cores; lowered after the machine went down, see the entry
on the cap below), so six workers share the eight cores.

**Reason:** one runner takes one job at a time. With every pull request sending three jobs of about twelve minutes each to
it, nine runs were queued within an hour and the runner was slower per pull request than the hosted ones, which run in
parallel. A pool of identical runners would fix the queue but let two Postgres jobs run at once, both binding the host
port 5432 for their service container; a label per job type keeps the ports apart by construction and still lets the three
jobs of one pull request run side by side. Memory carried it: one job at eight workers peaked at 5.2 GB of 19.9 GB with
swap unused.

**Trade-off, stated:** the three services run as one user with one rootless Docker. A job can therefore also read and change the
jobs running at the same time on the other instances (their `GITHUB_TOKEN` in `/proc/<pid>/environ`, their `_work`). The
boundary stays "the repository's own code only, reinstall after a malicious job"; one user and one Docker per instance would
close it at the price of three users, three daemons and three times the disk for images. The cleanup hook, which runs in that
shared Docker, removes only what is stopped, unused or old, never a running job's containers.

**Rejected alternatives:**
- One runner for everything, as installed first: a queue of hours as soon as several pull requests are open.
- Several identical runners: the port 5432 and 3306 collision between two jobs of the same type.
- A random host port for the service containers: it would need the jobs' connection URLs to follow, a change in the shared
  workflow for the self-hosted case only.


## The runner is capped, and it starts with one service

**Id:** a35df240-f14b-4468-8ab2-23b447a08175
**Type:** incident
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the first run of the three runner services, 2026-10-28 (the machine went down two and a half minutes after three jobs started; memory sampler, job timestamps and the boot log agree on the time); the coordinator's decision that evening
**Revisit when:** a test with the caps (one service first, someone watching) runs without a stall, or the CI moves to a machine that is not a workstation
**See:** process.md#one-runner-service-per-database-job-type-a-label-each-three-workers-per-job — c2713d54-e602-42a3-8636-693ff3fd2c0b — as of 2026-10-29

Every runner service carries `CPUQuota=150%`, `Nice=10`, low CPU and I/O weight, `MemoryMax=4G` and `-n 2`; the runner user's whole
slice, rootless Docker included, is capped at 4 of 8 cores and 8 GB without swap. The three services are started one at a time,
with the maintainer at the machine and a sampler running.

**Reason:** the first run of three uncapped services (nine workers, three database containers, three installs on eight vCPUs)
was followed within minutes by the stop of the machine, a VirtualBox guest on the maintainer's workstation, and by the loss of
three jobs. Memory was not it (one job peaked at 5.2 GB of 19.9 GB). That the cause is CPU starvation of the host is an
inference: the guest's journal of the crashed boot, read afterwards, ends five minutes after the jobs started with no error at
all, only two clocksource warnings of 3 s and 13 s gaps (the guest's CPUs did not run: a stall on the host, not a kill inside the
guest), and earlier crashes happened without CI. The caps make the
next test survivable whichever it is. The machine does other work: a second crash costs the agents their ops.

**Rejected alternatives:**
- A lower `-n` alone: it does not bound the database containers or three installs running at once.
- A cap on the units only: the containers of a rootless Docker run under the user's dockerd, outside the units' cgroups.
- Running the three services unattended after the first green test: a green test on a quiet machine says little about the
  load of several pull requests at once.


## Rented servers carry the runners for a week, one type each

**Id:** d621283e-1580-4220-8c72-ca1d5804d0aa
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's proposal as relayed by the coordinating agent, 2026-10-29 (the workstation stays for the agents; one to three rented servers act as runners for a week); his go, a Vultr dedicated-CPU plan of 8 cores and 16 GB for one week, was given in the project chat on 2026-10-29
**Revisit when:** the week is over, or a rented server stalls with the caps in place
**See:** process.md#the-runner-is-capped-and-it-starts-with-one-service — a35df240-f14b-4468-8ab2-23b447a08175 — as of 2026-10-29

The database jobs move from the maintainer's workstation to up to three rented Ubuntu servers (8 vCPU, 16 GB), one job type
per server, started with one server and `maria`, with 8 pytest workers on the dedicated profile (`dedicated-profile.sh`). The machine is prepared by `deploy/runner/bootstrap-server.sh` (runner user,
rootless Docker, a firewall chain for that uid) and the steps are in `deploy/runner/SERVER-SETUP.md`, run by the maintainer.
The caps of the workstation are replaced by drop-ins sized to the machine: the service may use 7 of 8 cores and 11 GB, the runner user's slice 7.5 cores and 13 GB, no swap.

**Reason:** the stall of 2026-10-28 took down the machine the agents work on; a machine that does nothing else loses
only CI when it stalls. One type per server keeps a stalled or compromised machine to one type, and each type binds its own host
port anyway.

**Rejected alternatives:**
- `pg` first, as planned for the workstation: `maria` is the slowest job (about 26 minutes hosted), so the gain is the biggest and the easiest to measure.
- The workstation caps unchanged: at 150% CPU per service eight workers would measure the cap, not the machine.
- All three types on one rented server: one stall or one malicious job takes all three, and the first test would again be
  the full load.
- No caps on the rented server: the cause of the stall is not established (see the entry above), and a runaway job should cost CI,
  not the machine's sshd; one core and about 3 GB stay free.
- A cloud autoscaling runner service: it needs a standing token with admin rights on the repository (see "Why not an ephemeral runner"
  in the runner README).


## HUB_RUNNER_TYPES: the jobs that go to the machine are named, the default stays all three

**Id:** 62a0fbc3-3f45-42ae-b33a-637373535070
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the plan to start the rented server with one job type only, 2026-10-29; the three `runs-on` expressions of `ci.yml`
**Revisit when:** all three types have a runner of their own, or the label prefix scheme changes
**See:** process.md#one-runner-service-per-database-job-type-a-label-each-three-workers-per-job — c2713d54-e602-42a3-8636-693ff3fd2c0b — as of 2026-10-29

An optional repository variable `HUB_RUNNER_TYPES` (a space-separated list of `sqlite`, `pg`, `maria`) names the database jobs that run
on the machine; unset or empty means all three, as before. A job whose type is not listed stays on a hosted runner.

**Reason:** `HUB_RUNNER_LABEL` alone sends all three jobs to self-hosted labels. With a runner for `maria` only, `hub-sqlite` and
`hub-postgresql` would queue for a runner that does not exist. A list keeps the default and the fallback (deleting the label variable
is still the whole fallback) and needs no change to the runners.

The list is matched as whole words (`contains(' <list> ', ' <type> ')`), and anything else (a comma, a stray newline, an unknown
name) matches nothing, so the job stays hosted: a mistyped variable costs speed, never a queued job waiting for a runner that does
not exist.

**Rejected alternatives:**
- One variable per type: three variables to set and to forget, and the fallback is no longer one deletion.
- One runner registered with all three labels: the three jobs would take turns on it, and the measurement of one type would be mixed
  with the others.
- A change of the workflow for the test only, reverted afterwards: a commit to main and a revert for what a variable does.


## The runner user is fenced by an owner-match chain on OUTPUT, replies first, loopback closed

**Id:** ca3532c5-f8f1-4687-b467-ee1b129dc603
**Type:** decision
**Status:** superseded
**Evidence:** inferred
**Superseded by:** 41cea0a5-28af-4a1a-87ad-aad00c580b77
**Source:** review of the setup package (two defects found by the reviewer, both reproduced in an unprivileged network namespace); re-check after the merge
**Revisit when:** the runner moves to a different container runtime or network stack, or a rented server shows the rules failing at boot
**See:** process.md#rented-servers-carry-the-runners-for-a-week-one-type-each — d621283e-1580-4220-8c72-ca1d5804d0aa — as of 2026-10-29

On a rented runner server one firewall chain (`MAITY_RUNNER`, IPv4 and IPv6) is jumped to from `OUTPUT` for packets of the runner user's
uid. Order: established and related connections return first; then only the two database ports on loopback and the local resolver
return; then everything else on `lo` is rejected (which includes the machine's own public address, routed over `lo`, so sshd on
0.0.0.0 stays out of reach); then the private ranges, link-local (the provider's metadata address) and shared address space are
rejected. The chain is rebuilt at boot by its own unit, which starts before the runner user's manager, and the runner units require
it, so a failed rule set stops the runner instead of leaving it open.

**Reason:** everything a job runs, rootless Docker and its containers behind slirp4netns included, runs under that one uid in the
host's network stack, so an owner match is the one place that sees all of it. The first version rejected loopback wholesale after the
two port exceptions: the replies of the database listener are packets of the same uid to a loopback address and were rejected, and
the machine's own address went over `lo` untouched. Both were reproduced in a network namespace before the fix.

The runner units get `Requires=`/`After=` on the firewall unit through a drop-in that `install-services.sh` writes only when
`maity-runner-firewall.service` exists: the same template serves the maintainer's workstation, which has no such unit, and a
`Requires=` there would keep the runner from ever starting. The firewall unit is ordered `Before=user@<uid>.service` (ordering
only), so at boot the runner user's rootless dockerd and slirp4netns start after the chain; a failed rule set then stops the runner
through its own `Requires=`, while the user manager still comes up and runs no job.

**Rejected alternatives:**
- `Requires=maity-runner-firewall.service` in the `maity-runner@.service` template: the workstation has no firewall unit and would
  never start its runner.
- A host firewall (ufw or a general policy): it would also hit sshd and the administrators, and does not single out the runner.
- A network namespace of its own for the runner: rootless Docker already builds one, and a second layer would have to be reached
  by the jobs' service containers on the loopback ports.
- Only the private ranges, without closing `lo`: the machine's own services stay reachable through its public address.


## A rented runner server takes SSH keys only, set with a timer that undoes it

**Id:** 834abe07-d857-418d-82a4-0247620a5566
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the first rented runner server (a provider image with root password login on, 2026-10-29); the coordinating agent's go for the change
**See:** process.md#rented-servers-carry-the-runners-for-a-week-one-type-each — d621283e-1580-4220-8c72-ca1d5804d0aa — as of 2026-10-29
**Revisit when:** the servers are reached through a bastion or a provider console that makes the public SSH port unnecessary

Right after the bootstrap, a drop-in `00-maity.conf` sets `PasswordAuthentication no`, `KbdInteractiveAuthentication no` and
`PermitRootLogin prohibit-password`; a systemd timer started first undoes the change after three minutes unless it is stopped after
both a key login and a refused password login were seen from a second connection.

**Reason:** the machine runs a public repository's CI and sits on a public address with root login by password on: that is the one
credential that needs no key. The drop-in is named `00-` because sshd takes the first value of an option and the provider's
`50-cloud-init.conf` sets the password login on. The timer is the second session of the usual advice, made safe against a
connection that is lost. The window is 180 seconds: long enough for two new logins from another machine, short enough to leave the machine
exposed only briefly if the change is wrong. The commands name Ubuntu's unit, `ssh` (other distributions call it `sshd`), and the last step stops the
timer and prints the three effective settings in one command, so a rollback that already ran is seen and not missed.

**Rejected alternatives:**
- Leaving the provider's default for a week: the password is random but the account is root and the port is open to everyone.
- Fail2ban or a firewall rule on port 22: it slows guessing, and the password login stays.
- Another SSH port: obscurity only, and the provider's console and the step list assume 22.
- Changing `50-cloud-init.conf` or `sshd_config` in place: cloud-init may rewrite its file, and the rollback would have to restore an edit instead of
  removing one file.


## Loopback is the job's own on a rented runner; ssh, the metadata service and the private networks stay closed

**Id:** 41cea0a5-28af-4a1a-87ad-aad00c580b77
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the first run of the database job on the rented server (2026-10-29): 69 of 3,241 tests failed that pass on the hosted runner, a probe as the runner user (a listener and a client on 127.0.0.1:34567 and :8025 were refused, :5432 worked, root worked), and the rules rebuilt in an unprivileged network namespace; the maintainer's decision for this option on 2026-10-29, relayed by the coordinating agent
**See:** process.md#the-runner-user-is-fenced-by-an-owner-match-chain-on-output-replies-first-loopback-closed — ca3532c5-f8f1-4687-b467-ee1b129dc603 — as of 2026-10-29
**Revisit when:** a job runs something that should not reach the machine's own services, or the servers carry anything besides sshd on loopback

The runner user is fenced by one chain, `MAITY_RUNNER`, that the `OUTPUT` chain jumps to for packets of that user's uid (an owner match: everything its jobs
start, rootless Docker and the containers behind slirp4netns included, runs under that uid in the host's network stack). In it, packets of connections that
exist already (replies) go first, so that a listener's answers are not judged as new traffic; `ssh` (port 22) is rejected over loopback and over the machine's own
address (routed over `lo`); the rest of loopback is the job's own; and the metadata service, the private ranges and shared address space are rejected. These
parts, the owner match on `OUTPUT` and replies first, are this entry's own decision now, taken over unchanged from the entry it supersedes; what changes is
loopback: "closed except the database ports and the resolver" becomes "open except ssh".

**Reason:** the suite starts servers of its own on loopback on any port (outbound-request tests, a TLS server with a wrong certificate, a mail
server for the notification tests), which the closed loopback refused: 69 tests failed that pass on a hosted runner. What the closed loopback
protected was sshd on the machine's own address (key-only since step 3b), the only service on the machine besides the resolver and the job's own
containers; the fence matters towards the provider's networks and the metadata service, which stay closed. A dedicated machine without secrets that is
reinstalled after a malicious job has little behind loopback to protect.

Because loopback is open to the runner user, the self-test at the end of `bootstrap-server.sh` lists every other listener on loopback, on the machine's own
address or on all addresses (ssh and the resolver excepted) as a note, not as a failure: a new service on the server should show at the next bootstrap
without blocking it. Rejected for that: a failure for every foreign listener (the distribution's own services would trigger it) and no check at all (the
"revisit when" of this entry would have no trigger). The probes run for 127.0.0.1, ::1 and the machine's own IPv4 and IPv6 addresses, because traffic to the
own addresses goes over `lo` and meets the same rule; the `::1` listener probe is skipped, with a note, where a provider has IPv6 off on `lo`.

**Rejected alternatives:**
- Opening more ports one by one (the database ports and the resolver, as before): the suite picks ports at random, and each new test server would be a new failure.
- Leaving loopback closed and moving the suite's servers elsewhere: they are in the tests, and a runner that needs the tests changed is not a drop-in for the hosted one.
- A network namespace per job: it would give the job its own loopback and keep the machine's closed, but rootless Docker already builds one, and a second layer would
  have to reach the service containers' loopback ports.
- Dropping the fence altogether: the metadata service and the provider's private networks are what a job must not reach.


## Only a push to main goes to the rented runner; pull requests stay hosted

**Id:** 2f1a3417-3e68-4241-a9b2-c113b7d2b93b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the queue at 16:15 UTC on 2026-10-29: one MariaDB job ran on the rented server, eleven waited, the oldest since 14:42, and four of the waiting runs were on `main`; the coordinating agent's decision for this option, the same day
**See:** process.md#one-runner-service-per-database-job-type-a-label-each-three-workers-per-job — c2713d54-e602-42a3-8636-693ff3fd2c0b — as of 2026-10-29
**See:** process.md#the-database-ci-jobs-may-run-on-the-maintainers-machine-a-forks-code-reaches-it-only-through-an-approval — 405c762c-11a2-4a95-a23b-0b2657a7aa8d — as of 2026-10-29
**Revisit when:** there are enough rented runners per job type for the queue of pull requests (one machine per concurrent job), or the jobs get random host ports

In `ci.yml` the three database jobs go to the rented machine only when the event is a `push` (to `main`); a `pull_request`, from this repository or from a fork, runs on a
hosted runner. The old condition (a pull request from this repository goes to the machine, one from a fork does not) is gone.

**Reason:** a runner does one job at a time and a job type has one runner, because the services bind the host ports 5432 and 3306. With pull requests on it
the queue of the MariaDB job reached eleven (about two hours of work) and `main`, whose checks are what a deploy waits for, queued behind pull requests
for over an hour. Hosted runners run pull requests in parallel, at about twice the time per job. The check that a merge is green is the one worth having
faster. This does not change the trust boundary: a pull request can change `ci.yml` and ask for the machine itself, so the approval setting for outside
contributors stays.

**Rejected alternatives:**
- Deleting the runner variable (everything hosted): safe, and it removes the queue, but the machine would do nothing.
- More runners for the same job type on one machine: two MariaDB jobs would both bind 3306 (random host ports would need the connection URLs to follow, a change in the shared workflow).
- A priority for `main` over pull requests: GitHub's queue has none for self-hosted runners; the split by event is what the workflow can say.
- Pull requests from this repository stay on the machine and `main` is brought forward (with `concurrency` or a runner group for `main`): `concurrency` orders within one group
  and does not prioritise across groups, and a second runner group for `main` needs a second runner per job type with ports of its own, the same problem as more runners on one machine.
- More rented machines: one more concurrent job each, at a cost; reasonable once the measured gain is clear and the pull request queue is the problem.


## A second rented machine serves the same job type under the same label and its own name

**Id:** 2020c6e7-f289-4d55-858a-5438c8bba239
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's decision to add a second runner machine (2026-10-29), after the queue of the MariaDB job (eleven waiting, the oldest for an hour and a half) showed one runner per job type to be the bottleneck
**See:** process.md#only-a-push-to-main-goes-to-the-rented-runner-pull-requests-stay-hosted — 2f1a3417-3e68-4241-a9b2-c113b7d2b93b — as of 2026-10-29
**Revisit when:** the queue is short again, or a job gets random host ports so that two jobs can share a machine

A second machine registers the same label (`maity-hub-maria`) and a name of its own (`RUNNER_NAME_PREFIX`, for example `maity-srv2` giving `maity-srv2-maria`). GitHub hands
a job to whichever runner with that label is free, so two MariaDB jobs run at once, one per machine.

**Reason:** a machine runs one job of a type at a time because the service containers bind the host ports 5432 and 3306; more concurrent jobs of a type need more machines.
The name of a runner must be unique in the repository (the first registration of the same name failed on the old workstation runners), the label is meant to be shared.

**Order:** the registrations of the old workstation runners with the default names (`maity-vm-<type>`) must be removed in the repository settings before a machine registers a name that collides; `config.sh` fails on a taken name and does not replace it. The default prefix stays `maity-vm`, so the first machine needs no new variable.

**Rejected alternatives:**
- A runner per job type on each machine, with the types spread over the machines (the first plan): it does not shorten the queue of the one slow job.
- Two services of one type on one machine: both bind 3306; random host ports would need the connection URLs to follow, a change in the shared workflow.
- A label per machine: the workflow would have to know the machines, and a job could not take whichever is free.


## The bootstrap's self-test reads the machine's own addresses without failing when one is missing

**Id:** fdcbc28e-c9ea-49ef-aa1b-c734e93c202a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the bootstrap of the second rented runner server, which stopped at the start of its self-test on a machine without IPv6 (2026-10-29, #648); the review of that change
**See:** process.md#a-second-rented-machine-serves-the-same-job-type-under-the-same-label-and-its-own-name — 2020c6e7-f289-4d55-858a-5438c8bba239 — as of 2026-10-29
**Revisit when:** the bootstrap also has to run on machines with IPv6 off in the kernel, where `ip6tables` in the firewall unit is the next thing to fail

`ip -6 route get` exits 2 ("Network is unreachable") where the provider gives no IPv6 route. Under `set -euo pipefail` the failing command substitution ended the whole
bootstrap at the start of its self-test, after everything was built and before it was tested, with neither a `FAIL` line nor a message, only the missing `ok:`. Both
lookups of the machine's own addresses now end in `|| own=` / `|| own6=`: an empty value keeps the script going, and every later use already skips an empty address.

**Reason:** the self-test is the last line of the bootstrap and a missing address is a normal case, not a failure of what was built. The earlier review of the IPv6 probe had named the case, but it had not been
tried on a machine without IPv6; the second server was the first one.

**Rejected alternatives:**
- Dropping `pipefail` for the script: it guards every other step.
- Checking for IPv6 first and skipping the lookup: a second test of the same condition, which can disagree with `ip route`.

