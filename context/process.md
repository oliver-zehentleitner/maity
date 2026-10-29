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

The condition in `ci.yml` that sends fork pull requests to the hosted runners is **not** a
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
through the repository variable `HUB_RUNNER_LABEL` (the prefix); unset, and for forks, the jobs run hosted. Each service
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
**Status:** open
**Evidence:** inferred
**Source:** the maintainer's proposal as relayed by the coordinating agent, 2026-10-29 (the workstation stays for the agents; one to three rented servers act as runners for a week); his go is still to come
**Revisit when:** the week is over, or a rented server stalls with the caps in place
**See:** process.md#the-runner-is-capped-and-it-starts-with-one-service — a35df240-f14b-4468-8ab2-23b447a08175 — as of 2026-10-29

Proposed, to run only on the maintainer's go: the database jobs move from the maintainer's workstation to up to three rented Ubuntu servers (8 vCPU, 16 GB), one job type
per server, started with one server and `pg`. The machine is prepared by `deploy/runner/bootstrap-server.sh` (runner user,
rootless Docker, a firewall chain for that uid) and the steps are in `deploy/runner/SERVER-SETUP.md`, run by the maintainer.
The same caps as on the workstation apply.

**Reason:** the stall of 2026-10-28 took down the machine the agents work on; a machine that does nothing else loses
only CI when it stalls. One type per server keeps a stalled or compromised machine to one type, and each type binds its own host
port anyway.

**Rejected alternatives:**
- All three types on one rented server: one stall or one malicious job takes all three, and the first test would again be
  the full load.
- A bigger or unlimited rented server: the cause of the stall is not established (see the entry above), so the caps stay until
  a test shows what the machine holds.
- A cloud autoscaling runner service: it needs a standing token with admin rights on the repository (see "Why not an ephemeral runner"
  in the runner README).


## The runner user is fenced by an owner-match chain on OUTPUT, replies first, loopback closed

**Id:** ca3532c5-f8f1-4687-b467-ee1b129dc603
**Type:** decision
**Status:** active
**Evidence:** inferred
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

**Rejected alternatives:**
- A host firewall (ufw or a general policy): it would also hit sshd and the administrators, and does not single out the runner.
- A network namespace of its own for the runner: rootless Docker already builds one, and a second layer would have to be reached
  by the jobs' service containers on the loopback ports.
- Only the private ranges, without closing `lo`: the machine's own services stay reachable through its public address.

