# Process

How Maity itself is built: the rules its own agents and maintainer work
by, where they differ from what the product prescribes.

## Pull requests get an independent first review on a different vendor's model; the coordinator decides, disagreements go to the maintainer

**Id:** 0b12c29d-1539-4737-9bc3-e5e5815238ec
**Type:** decision
**Status:** superseded
**Superseded by:** 297a0ea7-ebd0-4007-8b12-f839d005d205
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

## Before the deploy go, the lead puts every upgrade or setting note of the shipped changelog fragments on the deploy list

**Id:** 85c4ab14-7638-454f-b7fd-1ca1921c559a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request of 2026-11-05 to keep the lesson of the unset forge setting in `context/`, and the lead's rule for it, 2026-11-05
**Revisit when:** the deploy candidate's list is generated from the fragments by a tool, or fragments get a marker of their own for upgrade steps
**See:** incidents.md#a-setting-whose-unset-value-stopped-the-hub-reading-its-own-repository-went-to-production-unset — 2083a296-dac3-4164-b51e-9a3a6a38a26b — as of 2026-11-05

Before the deploy go, the lead greps the changelog fragments shipped
between the live SHA and the candidate SHA for upgrade and setting
notes ("set … when upgrading", a new or changed setting, an effect
while unset), and puts each one on the deploy candidate's test list as
a step done before the deploy. A pull request whose setting changes live
behaviour while unset names the setting and that effect in its body and
in its fragment, so the grep finds it.

**Reason:** the deploy list did not name the setting, although the
fragment of #1218 did (incident 2083a296), and the fragments are where a
change says what its upgrade needs. How that list was built is the
incident's inferred part, not this rule's.

**Rejected alternatives:**
- Leaving it to whoever deploys to read every merged pull request for
  new settings: that missed a setting whose note was in the changelog.

## When a reviewer returns, the cover's finished reviews stand and the returning reviewer takes the unstarted ones

**Id:** 8ba32bfa-41ff-4351-8884-4ac5ee08bae5
**Type:** decision
**Status:** superseded
**Superseded by:** eb392e3b-50bb-4dc5-ad3b-3e4b2272dbc0
**Evidence:** confirmed
**Source:** the coordinator's rule, 2026-10-22, set when the reviewer came back from a usage limit; superseded on 2026-11-04: the maintainer accepted the lead's recommendation "Ersetzt" (superseded) for req-whk2ez4r56f3 (seq 67806, relayed by the lead in seq 68775), after answering req-whk2ez4r56f3 itself with a question for a recommendation (2026-11-04); the lead's reason for the recommendation: there are no substitute reviewers any more. Its successors: the review lead hands out every review (since 2026-11-02), and no reviewer of another vendor stands in for an absent one (req-g5z43w1n2fkj, 2026-11-03)
**Revisit when:** a second reviewer joins, or reviews are reassigned in a way the board can show without a list from the coordinator
**See:** process.md#pull-requests-get-an-independent-first-review-on-a-different-vendors-model-the-coordinator-decides-disagreements-go-to-the-maintainer — 0b12c29d-1539-4737-9bc3-e5e5815238ec — as of 2026-10-22
**See:** process.md#an-absent-reviewer-vendor-gets-no-substitute-from-another-vendor-the-maintainer-is-told-and-the-review-waits — d9edf24e-9c27-4a2e-8c14-f4076a864c6d — as of 2026-11-04

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

## A change to the contract alone runs a light `hub-contract` part, not the database jobs

**Id:** 5b0f7a42-3c1e-4d68-9a15-e2c7d4f1b903
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's request of 2026-11-02 (review lead's finding that #1235, a pull request changing only `docs/api.md`, left main red with 2 failed tests); `.github/workflows/ci.yml`
**Revisit when:** a test opens `docs/api.md` in a way the grep does not find, or the gap below is closed, or the hub's database jobs get fast enough to take the contract path too

Three hub test files (`test_contract_routes.py`, `test_guide.py`, `test_paths.py`) read `docs/api.md`, but the `hub` part of the `changes` job
did not list it, so a pull request that changed only the contract got a green `ci-ok` and main went red after the merge. A new
part `contract` (`docs/api.md` and `hub/*`) starts the job `hub-contract`: `make install` and every test file that builds
the path `"docs" / "api.md"` (found by `grep` in the job, not listed; today `test_contract_routes`, `test_guide` and
`test_paths`) on SQLite, a few minutes. It is in `ci-ok`. A change under `hub/` starts it too, beside the hub jobs that run the same files: it answers in a few minutes, while the database
jobs take about an hour, and the coordinator asked for the filter `contract:docs/api.md` and `contract:hub/*`; a push to main and a change
to the workflow start it like every other part.

**Known gap (review of 2026-11-02):** hub tests also read files outside `hub/` and `docs/` (`web/tools/hub-shapes.json`,
`web/tools/site-fixture.json`, `deploy/Dockerfile`, `cli/src/maity/__init__.py`, `README.md`); a pull request that changes only
one of them starts neither the hub jobs nor this one. Not solved here; its own task.

**Rejected alternatives:**
- `docs/api.md` in the `hub` part: every contract pull request would run the PostgreSQL and SQLite suites, about an
  hour, for a few files that need neither a database server nor the rest of the suite.
- A fixed list of the test files: the first version listed two and missed `test_guide.py`, found in review; the job now
  selects them by the path they build.
- Moving the tests to the join-page gate or a script outside pytest: the tests stay where the hub's other tests are, and
  CI only chooses when to run them.

## Every agent uses Keep the Why: implementers record each decision in the same pull request, reviewers gate on it

**Id:** e534e9f3-a419-4a09-8054-117150592490
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's rule and reason, 2026-10-25, relayed by the coordinator; the maintainer's decision of 2026-11-04 to keep it beside the hub's requirement (req-3vww792gvj9q)
**Verification:** corroborated — re-checked 2026-11-04 after the hub began to require a why on code reports (§6.23): under `required` a code report without `why` is refused (`hub/src/maity_hub/routes/tasks.py`, `_check_why`), and a why is one of two forms: a reference to an entry, of which the hub checks only the shape, or `none` with a stated reason of at least ten characters; the hub never checks that the entry exists or that `ktw-lint` is clean
**See:** projects.md#keep-the-why-is-guaranteed-by-the-hub-a-commitment-at-resume-a-reminder-the-owners-notification-and-a-why-on-every-code-report — 7c1a4f0e-2b8d-4c6e-9a3f-5e2d8b7a1c90 — as of 2026-11-04
**Revisit when:** the hub checks that a report's why names an entry that exists and that `ktw-lint` is clean

Every agent building Maity works with Keep the Why. An implementer
writes a `context/` entry for each decision a pull request makes, in
that same pull request, with `ktw-lint` clean (one commit per entry
until 2026-10-27, see the entry on squash merges below). A reviewer
approves only after a Keep the Why gate: the entry is there and the
linter is clean, or, for a why of `none`, the stated reason holds. An
agent that writes
neither code nor reviews — one that rules on a question, for instance —
has its rulings recorded by the implementer of the change they decide,
not in a pull request of its own.

**Reason:** Keep the Why is part of the project, so every agent building
it uses it. The rule was first meant as the interim until the hub
guaranteed the same. Both stay now: the hub refuses a code report
without a why, and a why is either a reference to an entry, of which the
hub checks only the shape, or `none` with a stated reason (at least ten
characters). That the entry is there and the linter is clean, or that
the stated reason holds, is what the reviewer's gate checks.

**Alternatives:**
- The hub enforces it — a why reference required on code reports, set
  by policy per project. Chosen as the follow-up, not instead, and built
  since (the entry linked above); it stands beside the team rule, not in
  its place.

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

## The CLI's sdist and wheel are built from hashed, pinned tools in a job apart from the checks

**Id:** a8dd1473-5aff-4f32-a3fe-89c0498a208d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** hardening card tsk-ngx42j6r0jke (the maintainer, 2026-11-04; plan approved by the team lead); `.github/workflows/release-cli.yml`, `cli/requirements/release.in`, `cli/Makefile`
**Revisit when:** the CLI gains runtime dependencies, the build backend changes, or PyPI's trusted publishing starts attesting how the files were built
**See:** process.md#the-cli-is-published-to-pypi-as-maity-from-a-cli-v-tag-through-trusted-publishing — 227cd75c-bfc7-4cd8-9ba8-cf877cd3bf21 — as of 2026-11-04

What goes to PyPI is built only with `cli/requirements/release.txt`:
`build`, `twine` and the build backend `setuptools`, locked with hashes
by the uv that `hub/requirements/tools.txt` pins (`make lock`). The
release workflow's `build` job installs that lock alone, with
`--require-hashes`, into a fresh environment and builds without
isolation (`make release-build`). The checks run in a separate `check`
job with the unpinned dev tools; `publish` needs both and uploads only
the `build` job's artifact. `[build-system]` names the same exact
`setuptools` as the lock, so a build from the sdist uses the backend
the release was made with. The `cli` job of ci.yml runs `make
lock-check` (lock recompiled without its hashes, all three pins compared)
and `make release-build` on Python 3.11, and the audit workflow checks
the lock against the known advisories with the hub's locks. The lock
installs as wheels only (`--only-binary :all:`). The interpreter that
setup-python provides, with the pip it bundles (which checks the
hashes), is the trusted base and is not in the lock. The dev extra pins
the same `setuptools`, since the tests build without isolation in the
dev environment, where Python 3.11 bundles an older one; `lock-check`
compares all three pins.

**Reason:** the uploaded files are what every agent installs. Built
with whatever `build`, `twine` and `setuptools` PyPI served on the day
of the tag, a changed or replaced tool could change them unseen. A
hashed lock makes the build tools the reviewed ones. The build runs
without isolation: with it, `build` would set up its own environment and
fetch the backend again, without hashes. Keeping
the checks in their own job means nothing their dev tools install
shares the environment the files are built in. The hub already locks
its dependencies the same way (`hub/Makefile`), so the CLI reuses its
pinned uv instead of a second tool.

**Rejected alternatives:**
- Pinning only the build backend in `[build-system]`, building with
  isolation: `build` and `twine` themselves stay unpinned, and the
  isolated environment is resolved again on every run without hashes.
- One job for checks and build, as before: the dev tools, unpinned,
  run in the environment the files come from.
- Locking the dev tools too: they do not touch what is uploaded once
  the build is a job of its own; alternatives beyond that: unknown.

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
**Status:** superseded
**Superseded by:** none — the shared-budget working mode ended when the team moved to its own subscriptions (2026-10-27)
**Evidence:** confirmed
**Source:** the coordinator's notices of 2026-10-23 and 2026-10-24, passing on the maintainer's heads-up that the Claude agents would hit their usage limit
**Revisit when:** the usage limit has reset, or the budget stops being shared by the Claude agents
**See:** incidents.md#multi-agent-review-runs-exhausted-the-maintainers-monthly-budget — 1a5e729f-816a-4682-ab8c-a2029aa1ea0a — as of 2026-10-27

**Revisit:** the condition triggered on 2026-10-27: a new team runs on new
subscriptions, several Claude agents in parallel, on the maintainer's
instruction (coordinator, 2026-10-27). The coordinator re-checked this on
2026-11-01. This is not today's rule; the entry stays as the record of the
earlier stretch.

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
**Status:** superseded
**Superseded by:** https://github.com/oliver-zehentleitner/maity — c711af32-3678-406c-ac57-7a4fb3b3179f — as of 2026-10-30
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

The trigger in "Revisit when" came with #752: new migrations are named by
time, the author re-chains with `tools/rechain.py`, and CI fails on two
heads (entry c711af32 in `hub/context/persistence.md`), so neither the
reserved numbers nor the coordinator's order are needed any more.

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
model should not hold. Rule 14 of the agent skill says so. A resume
that omits `model` or `harness` keeps the previous session's value, so a
switch across such a resume is still seen.

The agent's own `maity resume` also prints one line when it changed the
model it had stored, `Model changed: <old> -> <new>, your lead is told.`,
and `maity wait` reads the event as `harness/model -> harness/model`.
The line was first left out, since the contract asked for none; the
coordinator's card for the CLI (tsk-5zev9p7dh680, 2026-11-01) asks for it,
and the contract's §13 now says so. Why the card wants it is not stated.

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
- Taking over only the previous `model` and not the `harness` of a resume
  that omits it: the session in between would hold no harness, and a
  switch from one harness to another over it would never be announced.

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

## The docs site is built from a hashed lock in a job with read access only; a second job that installs nothing publishes it

**Id:** b2e1d100-43c0-4655-aec2-b39ed2703d88
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-3t1tvkd5ktxs, pull request #1402 (plan approved by the team lead, the reasons below are the author's and the reviewers'); `.github/workflows/pages.yml`, `tools/requirements/site.in`, `tools/Makefile`
**See:** process.md — 7e78b0e4-e8b4-4ce2-9a83-f9457153cd5b — as of 2026-11-05
**Revisit when:** the site needs a tool without wheels, GitHub Pages deploys without an OIDC token, or pip installs from a standard lock (`pylock.toml`) without uv

The pages workflow has two jobs. `build` has `contents: read` only, checks out without stored
credentials, installs nothing but `tools/requirements/site.txt` (the Keep the Why dashboard,
Markdown, PyYAML; `--require-hashes --no-deps --only-binary :all:`) into a fresh environment,
makes the site and uploads it as the Pages artifact. `deploy` needs `build`, has no checkout and
installs nothing; of the two jobs only it holds `pages: write` and `id-token: write`. The lock is
compiled from `site.in` with the uv that `hub/requirements/tools.txt` pins (`make -C tools lock`);
`make -C tools lock-check` recompiles a copy without its hashes and fails on any difference. It
runs in ci.yml's `changelog` job, which installs uv from the tools lock the same way (hashed, no
dependency resolution, wheels only) and runs the docs renderer's tests from the site lock. The
audit workflow checks the site lock against the known advisories.

**Reason:** the rights to publish the site belong to the one step that publishes it, so the job
that holds them runs no code from the checkout and installs no package. The job that runs the
tools installs exactly the reviewed, hashed versions, and those change only when the lock
does. Wheels only, because an sdist would be built with build tools that are not in the lock. The
lock uses the same recipe as the hub's locks, so there is no second locking tool.

**Rejected alternatives:**
- One job with `pages: write` and `id-token: write`, as before: every step and every installed
  package ran with the rights to publish the site.
- Exact pins without hashes (`pip install markdown==… PyYAML==…`, the dashboard unpinned): pip
  installs whatever file the index serves for that version, and the dashboard's version could
  change on any push without a repository change.
- Installing the lock into setup-python's environment: whatever else is there shares it; a fresh
  environment holds exactly the lock.

## The database CI jobs may run on the maintainer's machine; a fork's code reaches it only through an approval

**Id:** 405c762c-11a2-4a95-a23b-0b2657a7aa8d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's go and the coordinator's brief (2026-10-28); the coordinator approved the plan; the security review of the pull request (2026-10-28) corrected the first version of this entry
**Revisit when:** the repository stops being public, a job needs a secret of the repository, or hosted runners get as fast as the machine

`ci.yml` lets `hub-sqlite` and `hub-postgresql`, and `hub-mariadb.yml` `hub-mariadb`, run on a self-hosted runner
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
**Source:** the bootstrap of the second runner machine, which stopped at the start of its self-test on a machine without IPv6 (2026-10-29, #648); the review of that change
**See:** process.md#a-second-rented-machine-serves-the-same-job-type-under-the-same-label-and-its-own-name — 2020c6e7-f289-4d55-858a-5438c8bba239 — as of 2026-10-29
**Revisit when:** the bootstrap also has to run on machines with IPv6 off in the kernel, where `ip6tables` in the firewall unit is the next thing to fail

`ip -6 route get` exits 2 ("Network is unreachable") where a machine has no IPv6 route. Under `set -euo pipefail` the failing command substitution ended the whole bootstrap at the start of its self-test, after everything was built and before it was tested, with neither a `FAIL` line nor a message, only the missing `ok:`. Both lookups of the machine's own addresses now end in `|| own=` / `|| own6=`: an empty value keeps the script going, and every later use already skips an empty address.

**Reason:** the self-test is the last line of the bootstrap and a missing address is a normal case, not a failure of what was built. The earlier review of the IPv6 probe had named the case, but it had not been tried on a machine without IPv6; the second one was the first.

**Rejected alternatives:**
- Dropping `pipefail` for the script: it guards every other step.
- Checking for IPv6 first and skipping the lookup: a second test of the same condition, which can disagree with `ip route`.


## Bugs are GitHub issues with a form; feature requests and contributions are directed to the project on Maity

**Id:** 3265e81c-616e-4c6d-9d27-5261e10d4691
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request on card tsk-mj2arrc90pgj, 2026-10-29; the wording of the forms is the implementer's
**Revisit when:** the public project page on Maity shows visitors more than the app shell, or outside contributors ask for a GitHub place for ideas

`.github/ISSUE_TEMPLATE/` holds one issue form for bugs (component,
version or commit, steps, expected, actual, logs with a reminder to strip
secrets) and a `config.yml` that turns blank issues off. Its contact
links send feature requests and contributions to the project on Maity
(`maity.team/oliver-zehentleitner/maity`) and security problems to the
private channel of `SECURITY.md`. Until the public project pages exist, a
visitor who is not signed in sees the app shell there, not the project.

**Reason:** Maity is built on Maity (see the entry on maity.team as the
only platform for the work): ideas and plans are discussed where the
project's agents and people are, and a bug is the one thing that is
better tracked beside the code, with the version attached. Blank issues
off keeps feature talk and vulnerability details out of the issue list.

**Alternatives:**
- Feature request and contribution forms on GitHub: a second place for
  the same discussion that the project's agents do not read.
- Leaving blank issues on: reports without a version or steps, and
  vulnerabilities posted in public.

## A load test runs on main and nightly, outside ci-ok; every review asks whether the load grows with history or with tabs

**Id:** bb9d58df-f795-4b3d-9351-6fc847250a22
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's decisions on card tsk-ryas52q9k53z (2026-10-30, messages 13710 and 13722); the first run of `hub/tests/test_load.py` on SQLite and on PostgreSQL 17 (local, 2026-10-30); `.github/workflows/hub-load.yml`
**See:** https://github.com/oliver-zehentleitner/maity — 24ca001c-ff28-4df3-8af1-ba6ef6d567b6 — as of 2026-10-30
**Revisit when:** the job's time on main is a problem or it goes red from noise rather than growth, or a pull request that changes the hot paths merges with no run behind it often enough to matter

`hub/tests/test_load.py` seeds the bell of one human with `MAITY_LOAD_UNIT` unread requests
(1000 in CI) spread over the 30-day window, asks the same of a history four times as large,
and fails when a call sends more statements (exact) or takes more than twice as long (and a tenth of a second more)
(soft: a CI runner is noisy). It covers a page of `GET /me/notifications`, marking a page
read, and one to eight held long-polls, each as a test on its own. It is its own workflow,
`hub-load`, on PostgreSQL: on every push to main, once a night, and by hand (`workflow_dispatch`)
on a branch that touches the load. It is not in `ci-ok` and does not run on pull requests.
The ordinary suite skips it through `addopts = "-m 'not load'"`; any `-m` on the command line
replaces that option, so `-m "not slow"` brings the load tests back and a run that selects by
marker has to repeat `not load`.

The first run found that a page of the bell is linear in the unread requests: 0.12 s at 1000
and 0.42 s at 4000 on PostgreSQL (0.08 s and 0.35 s on SQLite), with the same 52 statements
at both sizes; the cost is the Python derivation of every non-chat item of the window. That
test was `xfail(strict=True)` against `tsk-r8f0jm3xs9y6` until #678 paged every source of the
bell, and the marker went with it. A held long-poll sends 118 statements in three
seconds whatever the history (1000 or 4000 unread) and whether one or eight tabs hold one:
the stamp, not the derivation, is what a held poll repeats.

The question every review of a change to a listing, a poll or a worker asks: does the load
grow with the history, or with the number of tabs and sessions? An answer is a test that
holds it, or the reason it cannot grow. There is no separate reviewer brief; this entry is
where the question is kept.

**Reason:** the card is step 2 of the follow-ups to the 2026-10-26 overload, and asks for a
check that fails when time or queries per request grow with history or with tabs. A test can
compare two sizes of history on every run; a review is where a new route or worker is asked
the question before it ships.

**Rejected alternatives:**
- In the `hub-postgresql` job: it would add the seeding and the repeated timings to the run
  every pull request waits for, and CI time is the bottleneck.
- On every pull request, in `ci-ok`: a job that does not run on a pull request would block
  those it skips, and a timing failure from a noisy runner would hold up unrelated merges.
- Absolute limits in seconds: they depend on the runner and say nothing about growth; the
  comparison of two sizes does.
- Skipping the load tests through an environment variable instead of a marker: the marker is
  what `-m load` and the `hub-load` job select by, and a test skipped by a variable would run
  silently once someone sets it.

**Known limit:** the time check allows twice the time and at least a tenth of a second more, so a
growth smaller than that is not seen (the page's 3.5 times is well past it); the statement count is the exact half. The seeded
history is one human and one project with one kind of item (requests).

## The newcomer doc states CLI behaviour from cli.py's help, not from memory

**Id:** 7cc9feea-3b89-4e54-b7d8-0f4dc1f09880
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** review findings on #755 by agt-2dkh5tfqppxd and agt-mbf0gthrsash (2026-10-30); task tsk-hzjqn875bcmt
**See:** https://github.com/oliver-zehentleitner/maity — 7cc9feea-3b89-4e54-b7d8-0f4dc1f09880 — as of 2026-10-30
**Revisit when:** CLI documentation is generated directly from `cli.py` argparse definitions

When revising agent documentation (`docs/agents.md`), CLI command options and defaults
must be verified directly against `cli/src/maity/cli.py` and `cli/README.md` on `main`,
never from an agent's memory or an older locally installed CLI binary.

#755 originally described the earlier `wait` default (`--one` behavior) as current because
an agent's local environment may hold an older package than the repository's HEAD where
`maity wait` outputs a JSON array by default. Likewise, `--kind` is documented with its side
effect (other kinds are read past and acknowledged at the hub unseen, as `cli.py` states), so
that a newcomer does not filter away assigned cards or answers.

**Reason:** CLI behavior evolves rapidly during development; verifying documentation against
in-tree source definitions prevents subtle discrepancies for newcomers reading the guide.

**Rejected alternatives:**
- Generating `docs/agents.md` automatically from argparse: excessive tooling overhead for a
  single curated markdown guide that balances newcomer prose with command reference.

## Every pull request needs two approvals, one from a Grok reviewer and one from an Antigravity reviewer, and a green `ci-ok` on the exact head

**Id:** 297a0ea7-ebd0-4007-8b12-f839d005d205
**Type:** decision
**Status:** superseded
**Superseded by:** c73e26c4-60b2-49e7-9df8-278fca4fcb2e
**Evidence:** confirmed
**Source:** the maintainer's decision in the hub chat, 2026-10-29 ("then let's rather have everything checked twice, by one Grok and one Antigravity"); the coordinator's merge practice since then
**Revisit when:** a reviewer family is unavailable for long, the ChatGPT-based reviewers return and could stand in for one side, or two approvals turn out to miss what one more careful review would catch
**See:** process.md#the-coordinating-agent-manages-merges-and-releases-it-does-not-code-review-or-test-and-it-routes-work-by-model — 11b7ed4d-100d-490f-ab34-c68ace8b5f80 — as of 2026-10-30

Before the coordinator merges a pull request, one instance of the Grok
reviewer and one instance of the Antigravity reviewer have each
approved it, both models of other vendors than the coders'. After
rework, the reviewers check the delta against their findings. The merge
waits for the summary check `ci-ok` to pass on exactly the head that is
merged. The coordinator compares a sample of each review's claims —
names, files, quoted lines — with the diff; an approval built on facts
the diff does not contain does not count until it is corrected.

**Reason:** the ChatGPT-based reviewers had run out of usage. In the
first morning with only Antigravity reviewing, one approval missed a
finding that Grok then caught, and Grok once withdrew a wrong finding of
its own; two independent model families catch what one misses. A
reviewer that invents content is caught by the sample check, not by a
second review alone.

**Rejected alternatives:**
- One review on another vendor's model (0b12c29d) — the morning of
  2026-10-29 showed a single pass missing a real finding.
- Merging when no check is red — the hub and end-to-end jobs report only
  after the change detection, so a pull request can look clean with only
  the quick checks run.

## Every pull request needs an approval from all three reviewer vendors, Antigravity, Grok and ChatGPT, on the exact head, and a green `ci-ok`

**Id:** c73e26c4-60b2-49e7-9df8-278fca4fcb2e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision at the jour fixe of 2026-11-03, relayed by the lead on 2026-11-04; it follows the rule of the same morning, two of three vendors, set when every Antigravity instance ran out of quota at once
**Revisit when:** a reviewer vendor is unavailable for long, or a fourth vendor joins
**See:** process.md#every-pull-request-needs-two-approvals-one-from-a-grok-reviewer-and-one-from-an-antigravity-reviewer-and-a-green-ci-ok-on-the-exact-head — 297a0ea7-ebd0-4007-8b12-f839d005d205 — as of 2026-11-04

Before a pull request is merged, one reviewer of each vendor, Antigravity,
Grok and ChatGPT, has approved exactly the head that is merged, each in a
fresh context of its own. After rework the three review the delta, and a
fix is pushed once all three results for the current head are in, not
after the first. The merge waits for `ci-ok` on that head, and a sample
of each review's claims is still compared with the diff before it counts
(the entry linked above).

**Reason:** the maintainer's: quality before speed. Two of three was the
interim of one morning, while one vendor was out of quota.

**Rejected alternatives:**
- Two of three vendors, the third awaited when it can be: the morning's
  interim, replaced at the jour fixe the same day.
- One Grok and one Antigravity reviewer (297a0ea7): the ChatGPT
  reviewers are back, and a third vendor's view is wanted on every pull
  request.

## The review lead's team hands out every review

**Id:** eb392e3b-50bb-4dc5-ad3b-3e4b2272dbc0
**Type:** decision
**Status:** active
**Evidence:** unknown
**Source:** the rule of the previous lead, 2026-11-02 (the review lead coordinates every review, seq 36181), narrowed by the current lead on 2026-11-03 (review requests and head SHAs go to the review lead alone, no copy to the lead, seq 50518); the request's form, base and head SHAs in full, from the lead's assignment rule after the jour fixe of 2026-11-03 (seq 54855); confirmed by the lead on 2026-11-04
**Revisit when:** reviews are to be requested from a vendor directly again, or the review lead's team is unavailable

A coder sends a review request, with the base and head SHAs in full, to
the review lead and to nobody else. The review lead's team picks the
reviewer of each vendor, orders the reviews and delta reviews, checks
the results, and collects the minor findings (P3) for the area's
collection card. Merges, deploys and cards stay with the lead.

The rule itself is confirmed by these sources; its reason is not, so
the entry's Evidence is the weaker grade.

**Reason:** unknown — not recorded with the rule.

**Alternatives:** none recorded. Before 2026-11-02 the coordinator
gave the order of the reviews (8ba32bfa, for a returning reviewer); why
that changed was not recorded.

## An absent reviewer vendor gets no substitute from another vendor; the maintainer is told and the review waits

**Id:** d9edf24e-9c27-4a2e-8c14-f4076a864c6d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's answer of 2026-11-03 (req-g5z43w1n2fkj) to the question whether a reviewer of another vendor may stand in while one is out
**Revisit when:** the maintainer allows a substitute for a vendor that is out, or a vendor is out for longer than a release can wait
**See:** process.md#every-pull-request-needs-an-approval-from-all-three-reviewer-vendors-antigravity-grok-and-chatgpt-on-the-exact-head-and-a-green-ci-ok — c73e26c4-60b2-49e7-9df8-278fca4fcb2e — as of 2026-11-04

When a reviewer vendor is unavailable (out of quota, offline), its review
is not handed to another vendor's reviewer. The maintainer is told at
once, through his inbox, and the pull request waits until he restores the
reviewer or reorganises the reviews.

**Reason:** the maintainer's words: he wants to keep the quality, and
building well and solidly matters more to him than building very fast.

**Rejected alternative:** a substitute reviewer of another vendor while
one is out: faster, but it lowers the three-vendor gate the entry above
sets.

## The ci runs on main share one group: one runs, the newest waits, none is cancelled

**Id:** fc23b250-320b-4f5b-b9a9-87fdcb01d727
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's approval, 2026-10-31 (request req-8zh1rkez993w), after twelve main runs queued at once, one per merge
**Revisit when:** the runs on main get so short that a queue cannot form, or a deploy needs a green run for a specific older commit

`.github/workflows/ci.yml` gives every push to main the same concurrency group and does not cancel a run
that has started. GitHub then keeps the running run and replaces a run still waiting by the newest one, so at
most one main run runs and one waits. Pull requests keep their own group per pull request, as before, and a new
push to a pull request still cancels its older run.

**Reason:** every merge started its own run, each checking an outdated commit, and the database jobs on the rented
runners held the machines that the pull requests behind them waited for; the coordinator cancelled twelve runs by hand.
Only the newest main commit matters for a deploy, so the runs in between were work nobody read.

**Consequence:** a commit that merged while a run was waiting has no `ci-ok` of its own: GitHub cancels its waiting
run and shows it as cancelled, which is not a failure. A deploy takes the newest commit with a green run, or waits
for the newest run to finish.

**Rejected alternatives:**
- `cancel-in-progress: true` on main: a streak of merges would cancel each run before it finishes, so main could stay without a
  green run for as long as the streak lasts, and a deploy needs a green one.
- A group per commit, as before: nothing is ever replaced, so a merge streak queues one run per merge.

## Every CI job has a timeout, 90 minutes for the database jobs and 30 for the rest; a hang no longer holds main for six hours

**Id:** 97f338fd-9f05-4376-ac74-1649931c9945
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's decision, 2026-11-02, after main's ci run of `2246df68` hung in `hub-postgresql` at 99 % from 17:08 UTC until GitHub's six-hour limit cancelled it at 22:22 UTC (no ci run on main finished from 14:43 UTC on; the search for the hanging test is card tsk-xz3bxa5cwv4v); job durations read from the run history
**Revisit when:** a green database job runs longer than about 70 minutes or another job longer than about 20, or the jobs move to slower runners

`hub-sqlite`, `hub-postgresql` (`ci.yml`) and `hub-mariadb` (`hub-mariadb.yml`) carry `timeout-minutes: 90`; every other job
`ci-ok` waits for carries 30 (`web-e2e` keeps its 15). Without it a job runs to GitHub's limit of six hours; while main's one
running ci run hangs, every newer push only replaces the waiting run (the entry above), so nothing on main finishes and the
MariaDB start from `ci` never comes. Green runs of the last day took up to 42 minutes (SQLite), 64 (PostgreSQL) and 29
(MariaDB, on the rented runners); the other jobs up to 17 (`cli-windows`), most of them under 10. 90 and 30 leave room for a
slow runner and still fail a hang the same evening.

A timeout ends the job as `cancelled`, not `failure`, and the run shows as cancelled in the run list, like a run GitHub
replaced while it waited; `ci-ok` counts only `success` and `skipped`, so it is red. In `hub-mariadb.yml` the report treats
`cancelled` like `failure` and opens or comments on the `ci-red` issue, since nothing there cancels a running job; before, a
hung MariaDB run ended without a word.

**Rejected alternatives:**
- A per-test timeout (`pytest-timeout`): names the hanging test, which the job timeout does not, but is a new dependency in the
  locks and a choice of a limit per test; it belongs to the search for the hang, not to keeping the queue moving.
- Cancelling a hung run by hand: needs someone to notice it, and here nobody did for five hours.
- The timeout on the three database jobs only: a hang in any job `ci-ok` waits for holds main the same six hours, and
  GitHub has no timeout for a whole workflow.

## hub-postgresql prints every thread's stack when a test runs longer than 300 seconds

**Id:** 32d51f7e-a3dc-4027-9ceb-ce2a0ecdca69
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-80xk3tbhe2hc, from the jour fixe of 2026-11-03 (request req-tmx2jadxrqvt, adopted by the maintainer); the lead's message that a hang on #1225 ended as a silent 90-minute timeout (not checked here); the diagnosis run on #1255 (`-o faulthandler_timeout=300`, its stacks in `hub/context/testing.md`); the proof run on #1316, 2026-11-04
**Revisit when:** a green `hub-postgresql` test runs longer than about 120 s, the stacks come from tests that do not hang, or `pytest-timeout` comes into the locks for another reason
**See:** process.md#every-ci-job-has-a-timeout-90-minutes-for-the-database-jobs-and-30-for-the-rest-a-hang-no-longer-holds-main-for-six-hours — 97f338fd-9f05-4376-ac74-1649931c9945 — as of 2026-11-04

`hub-postgresql` (`ci.yml`) sets `PYTEST_ADDOPTS: -o faulthandler_timeout=300` in the job's environment. A test whose
setup, call and teardown together run longer than 300 s makes its worker print the stack of every thread into the job log,
once, and the test runs on: a slow test that ends still passes, and a hang still ends at the job's 90 minutes. The log then
already holds the frame and the line the hang waits on, which the cancel alone never shows. The dump holds frames only:
when the call hangs, the test function's frame names the test; when a fixture hangs in setup or teardown, it shows the
fixture (as on #1255, the fixture `engine`, waiting in `_empty_the_tables` under `pytest_runtest_setup`), and without
`-v` nothing else in the log under `pytest-xdist` names the test. The job does not add `-v`: with it the #1255 log grew to
about 1.5 MB, and the fixture's frame is what the search for a hang starts from.

300 s because: the setting only prints, so a value too low costs a block of log and nothing else, and a value too high
costs waiting; the cleanup between tests waits up to 60 s for a lock before it ends a leaked connection
(`TRUNCATE_LOCK_TIMEOUT`, `hub/context/testing.md`), so a limit needs room above that; the diagnosis run on #1255 used
300 s and found the hang's stacks (that run also had `-v`, which named the test; this job does not, see above); 300 s is
an eighteenth of the 90 minutes, so a hang shows where it waits early in the run.

**Rejected alternatives:**
- `pytest-timeout`: it would also fail the hanging test, but it is a new dependency in the locks; the entry above rejected
  it for the queue, and the stack is what the search for a hang needs. `faulthandler_timeout` is part of pytest.
- `faulthandler_exit_on_timeout` as well (built into the pinned pytest, no new dependency): the worker exits after the
  dump, `pytest-xdist` reports "worker crashed while running <test>" as failed, which names the test even when a fixture
  hangs; after 5 minutes the log shows an F and the worker going down; the summary at the end of the run names the test.
  The job does not end sooner: `pytest-xdist` replaces the crashed worker and the run goes on, so the job goes red only
  when the rest of the suite is done. Not
  taken: a slow but finite test past 300 s would then fail, and the value was chosen as a print threshold, not as a
  limit a green test must stay under. (The author's own reading, not the card's words: the card says only "Kostet
  nichts, solange nichts hängt", and a setting that fails a slow green test costs something.)
- In `[tool.pytest.ini_options]` of `hub/pyproject.toml`: every local and SQLite run would print stacks too, past the
  scope the jour fixe decided; the job's environment keeps it to `hub-postgresql`.
- On the `make test` line (`PYTEST_ARGS`): repeats the Makefile's `-n auto`, and a later change to that line drops the
  limit unnoticed.

`hub-mariadb` (`hub-mariadb.yml`) also runs `make test` under 90 minutes, and the cleanup's lock timeout is PostgreSQL
only, so a leaked lock there is not bounded by the suite. It stays out here: the card and the jour fixe named
`hub-postgresql`, the job where the hangs were seen; MariaDB runs on main outside `ci-ok`, and a timed-out run already
counts as red and opens a ci-red issue (the entries on the timeouts and on MariaDB). No hang on MariaDB has been
reproduced; the same line there is open for a later card. `hub-sqlite` has no server locks between sessions.

Which reasons are confirmed and which inferred: that the setting prints the stack under `pytest-xdist` and the test still
passes is confirmed (proof run on #1316, and a local counter-check without the setting printing nothing); that a setup
hang's dump itself names no test is confirmed by the #1255 log and by a local reproduction in the review of #1319; that
without `-v` nothing else in the log names it is confirmed by that reproduction only, since #1255 ran with `-v`; the
value is the author's weighing, not measured against a real hang beyond #1255.

## MariaDB checks main after every ci run and every hour, not every pull request; PostgreSQL and SQLite stay in the gate

**Id:** 75a2382c-6a3d-450d-873e-8aade80d6e3b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-31 (left to the coordinator), on card tsk-p7dfb6e9p5wz, after the database jobs had grown to 60 to 90 minutes a run
**Revisit when:** MariaDB breaks on main often enough that the checks after each push and the hourly clock find it too late, or the suite gets fast enough to be a gate again

The hub's test suite against MariaDB left `ci.yml` and `ci-ok`. `.github/workflows/hub-mariadb.yml` runs it on main after
every finished `ci` run and at the latest once an hour, and only when files under `hub/` (or the join page doc, or the workflow itself) changed since the
last green automatic run; a quiet hour is skipped. `hub-postgresql` (what production runs) and `hub-sqlite` stay per
pull request and in `ci-ok`.

**The clock is not enough (2026-11-01):** (Source: the coordinator's finding, 2026-11-01, that scheduled runs were skipped, visible in the run history of the workflow; the start from the last job of `ci.yml` was decided by the coordinator on 2026-11-02 in the review of the pull request that added it, after the first version with `workflow_run` was found to break the runner rule.) GitHub starts scheduled workflows on a best-effort basis; in the first nine hours
after the merge only one scheduled run happened (and not at the minute asked for). Every push to main therefore also
starts the workflow, from the last job of `ci.yml` (`gh workflow run` with `trigger=ci`, a `workflow_dispatch` with the workflow's own token), with the same checks: one running, one waiting, skipped when nothing relevant changed. The
clock stays as the fallback for quiet days. "Automatic run" below means the clock or a start from `ci`; a hand start is not one. Both a start from `ci` and a hand start are a `workflow_dispatch`, so the run title (`hub-mariadb ci` or `hub-mariadb hand`) tells them apart where the run list is read.

**What keeps it from rotting:** a red run opens one issue labelled `ci-red` that names the commit range since the last
green run, and later red runs comment on it, so the change that broke it is found within the hour; a green automatic run
closes it, but only when the green commit contains every commit the issue names as red (a hand run on a newer commit may have opened it). The next hour always runs again after a run that did not end green or while the issue is open, so a revert
closes the issue and a failure outside the watched files is not skipped over. A deploy or release is not allowed past a red MariaDB: the run is started by hand for that commit
(Actions, hub-mariadb, Run workflow, with the sha), and its result is read before the deploy.

**Reason:** MariaDB is the self-hoster's database and the slowest suite; held in front of every merge it made main's
runs queue for an hour and more while the code it checks changes rarely in ways that break only there (the migration
of 2026-10-29 that only MariaDB rejected is the kind of fault it is for). An hourly clock on main keeps the
fault close to the change that caused it without making every author wait for it.

**Rejected alternatives:**
- Keep it in the gate and add runners: more machines for a suite whose value is the daily catch, not the per-PR one.
- Nightly only: the culprit would sit among a day of merges instead of an hour's.
- Remove it: self-hosters on MariaDB would learn about a break from their own upgrade.
- One concurrency group for the automatic runs and the hand start: GitHub keeps one waiting run per group, so a hand start for a
  deploy candidate would be displaced by the next automatic run while it waits behind a running one; they have a group each.
- A `workflow_run` trigger on `ci` (the first version of the pull request): `deploy/runner/README.md` says that no workflow of this
  repository uses `workflow_run`, and with reason: `branches: [main]` compares the head branch name, so the `ci` run of a
  fork's pull request from a branch called `main` would start it, with a write token in the report job and on the
  maintainer's machine. The rule stays; `ci` starts the run itself (below). Found in review, decided by the coordinator, 2026-11-02.
- A `push` trigger on main in `hub-mariadb.yml`: the run would start beside `ci` instead of after it and compete with it for
  the same machines, and it would start for a commit whose `ci` is still going.
- Starting it from `ci` only after a green `ci`: a red `ci` on main would then pause the MariaDB check entirely, and a red
  state is what it is for; the last job of `ci.yml` runs whatever the result of the jobs before it.
- One group per trigger (`github.event_name`, the first version): the clock and a finished `ci` run then do not queue behind
  each other, both decide at once against the same last green run, and the suite starts twice for one commit; the two
  automatic triggers share one group.
- Counting a `cancelled` run as the last result: a waiting run that a newer one replaced in the queue ends `cancelled`
  and sorts ahead of the run that is still going, so the next `decide` would see "the last run was not green" and run
  although nothing relevant changed; `cancelled` is left out when the last result is read, and the diff base is still the
  last green run, so no change goes untested.
- Any commit for a hand start: the sha is free text and a commit of a fork's pull request can be checked out by it, which
  would run it on the self-hosted machine without the approval of outside collaborators; only commits of main are accepted.
- Notify agents directly from the workflow: that needs a Maity credential in the repository's secrets; the issue is the
  channel the workflow can use without one.

## Before the launch the contract says what runs, and nothing is built only to fulfil it

**Id:** 55dd3656-2dbe-4c9b-bca6-5b3505545b92
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's decisions on the contract follow-ups, 2026-11-01; the follow-up list of #1094
**Revisit when:** the launch is out

Where the contract promised what the hub does not do, the passage stays as the
agreed design and is marked "not built", as for the objection hold (§6.19) and
a participant's `wake` (§9.2). Exceptions the hub already has, such as the
`204` answers, are listed instead of changed.

**Rejected:** building the missing routes now, which adds risk right before the
launch for features nobody has asked for yet; deleting the passages, which would
lose agreed designs.

## The docs pages on maity.dev are rendered at deploy from `docs/`, and `docs/nav.yml` is the only list of pages and the navigation

**Id:** 3b470500-85e0-4261-996e-425290e5d97b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request for a docs page on maity.dev; the joint proposal of the designer and the docs author on the card tsk-92pgshcs2a8c, 2026-11-01. The reasons are theirs, not stated by the maintainer.
**Revisit when:** the docs become multilingual, or need pages without a Markdown source
**See:** process.md — 7e78b0e4-e8b4-4ce2-9a83-f9457153cd5b — as of 2026-11-01

`tools/site_docs.py` renders every page `docs/nav.yml` lists when the site
deploys, with GitHub's anchors, so links from the repository and from the
site are the same. A section `hide` names on a split page gets no page.
`docs/architecture.md` stayed out of the list while it still described the
first design of 2026-10-21 (the lead's call on #1095); since its rewrite to
main (#1389, #1396) it is listed under Reference as "Architecture".

**Reason:** the repository and the site would otherwise drift apart, and
each command is checked only once.

**Rejected:**

- Pages written by hand in HTML: a second source.
- A static site generator with Node or a framework: more tooling than about
  ten pages need.
- Linking only to the Markdown on GitHub: no navigation of its own, and
  `docs/api.md` as one page of 17,000 lines.

## Docs images and diagrams live in `docs/img/`; screenshots are of fixture mode, and the site points a relative image at the deployed file

**Id:** 7f3f6220-0bf0-4d81-8521-5761b877a1dd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** pull request #1325 on the card tsk-92pgshcs2a8c, 2026-11-04: the designer's screenshots and `tools/site_docs.py` change, the designer's account of how they were made and what was weighed, and the three reviews (the size and this entry asked for there). Pull request #1353 on card tsk-dremqrfz48jq, 2026-11-05: the designer's statement that the diagrams are drawn by the designer, take the same 256-colour and oxipng reduction as the screenshots, and that their source stays with the designer
**Revisit when:** `.github/workflows/pages.yml` stops copying `docs/` to the site's root, the docs site gets a build step that collects images itself, or the screenshots are made by a script
**See:** process.md#the-docs-pages-on-maitydev-are-rendered-at-deploy-from-docs-and-docsnavyml-is-the-only-list-of-pages-and-the-navigation — 3b470500-85e0-4261-996e-425290e5d97b — as of 2026-11-04

The images of the docs pages are files in `docs/img/`, linked from the
Markdown with a relative path, so they show on GitHub as on the site.
`tools/site_docs.py` rewrites a relative image the way it rewrites a link:
one under `docs/` points at its path at the site's root, which exists only
because `pages.yml` copies `docs/` there; any other at GitHub's raw file.
Only the path is normalised; a query or fragment stays as written.

The screenshots show the dashboard in fixture mode, never a hub with real
accounts, so they carry no names, addresses or tokens: `web/index.html`
opened as a file, at `#/new`, `#/all` and `#/maintainer/maity/board`, in
Chromium (Playwright) at 1280 px with a device scale of 2, the light
scheme and the clock in UTC (the inbox shows its times in the browser's
zone). For all three, the sign-in notice is answered with **This was
me** first and injected CSS hides the "Fixtures" badge (`.source`). For
the inbox and the form it also hides any `.flag`; after the answer those
two pages have none left. The inbox is cut 24 px below its first entry's
button row, the form just below the Project memory hint. The board, from
the pull request's first set, is the 1280 × 760 px viewport from the
top, with no `.flag` hidden, so it shows a card's "Waits for an answer"
box. Each is scaled to 1600 px
wide and reduced to 256 colours (libimagequant, then oxipng level 4)
before it is committed: about 290 KB for three instead of 734 KB, since
every version stays in the history. The designer's script is not in
the repository yet.

Diagrams in the same directory are drawn by the designer, and their
source stays with the designer. They take the same reduction as the
screenshots: 256 colours with libimagequant, then oxipng level 4. The
repository does not redraw them or change their width.

**Reason:** a page and its pictures come from the same place, like the
text (the entry linked above), and fixture data is the one dashboard
state that holds nothing private.

**Rejected:**

- GitHub's raw file for the images under `docs/` too: the site would
  depend on another host, and so would every fork or copy of it, while
  `pages.yml` puts `docs/` at the root anyway.
- A second copy in `docs/_assets/`: the same file twice, at a path other
  than the `img/…` GitHub shows when it renders the Markdown.
- Dark variants through `<picture>`: GitHub's Markdown needs raw HTML for
  it, and the site is light unless the reader's system asks for dark
  (`tools/site_docs/docs.css`), so the designer judged one light set
  enough.
- Screenshots of a real hub: real names and data in the repository; the
  fixtures exist for this.

## On a shared development machine, PostgreSQL runs share one server, and at most two smoke or PostgreSQL runs go at a time

**Id:** c9165811-5049-4d24-9564-49669ad385a1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions at the jour fixe of 2026-11-03 (a PostgreSQL run before review for every hub change with a migration or raw SQL; one shared server and a cap on parallel runs), card tsk-7f9064s936kf
**Revisit when:** contributors no longer share one machine and account, the shared machine gets enough memory for more parallel runs (two runs at once no longer bring a reap near), or CI checks a pull request's merge with the current main on PostgreSQL before review

A hub change that adds or changes an Alembic migration or raw SQL runs the tests it affects on
PostgreSQL before it asks for review, and the reviewers run them there too or say that they checked
on SQLite only. On a machine several contributors share under one Unix account, those runs use one server, which
`hub/scripts/with_postgres.sh --start` leaves up. Each run gets a throwaway database of its own,
named after whoever runs it. `make smoke` and `with_postgres.sh` each hold one of two run slots
(`tools/run_slot.sh`, a lock file per slot), so a third run waits instead of starting. The commands
are in `CONTRIBUTING.md`, "PostgreSQL runs and a shared machine".

**Reason:**
- SQLite does not show PostgreSQL's errors, and CI as the first PostgreSQL run finds them only
  after the review.
- Each contributor starting a server of their own, or running beside everyone else, pushed the
  shared machine into memory reaps. The reaps ended other members' long-running processes without
  their noticing.
- A database per run keeps runs from seeing each other's tables on the one server.
- A slot is held by an inherited file descriptor, so it lasts exactly as long as the command and
  everything the command starts. The server itself is started with that descriptor closed, or it
  would hold a slot for as long as it runs.
- The command inherits the server lock the same way. A memory reap ends the wrapper with SIGKILL
  and its command can live on; with the lock it still counts as a run, so `--stop` and the last
  run's cleanup leave the server up under it (found in the review of #1302). The cleanup asks
  through a file of its own: on the shared descriptor its exclusive lock would only convert the
  lock the command's leftovers hold, and once the wrapper ended they would hold it exclusively,
  and every later run, `--start` and `--stop` would hang (found in the same review). The cost:
  something the command leaves running keeps the server up, `--stop` refused and its run slot
  taken until it ends, so two such processes leave no slot free; other runs still get the server.
  The slot's `.who` file in the run-slot directory names the run it came from.
- The slots and the server are files of one account (the data directory is the owner's only), so
  they bind the runs of that account. That is how the machine is shared; several accounts would
  each get two slots and a server of their own.

**Rejected alternatives:**
- A server per contributor: what was done before, and what used the memory.
- A new tool around the `pgserver` package: `with_postgres.sh` already shared one server between
  runs and stopped only a server it started. It needed a start for every run of the account, the
  run slot and the database name, not a second way to do the same.
- The command without the server lock, a run counted by its wrapper alone: what #1302 had first.
  A reap kills the wrapper and leaves the command running, which then had the server stopped under
  it.
- A third run that fails: the run would have to be started again by hand, so it waits and says
  who holds the slots.
- A cap in CI: each CI runner already has its own limits (the runner entries above), and the card
  left CI out.

## An opt-in pre-push hook runs CI's lint and types for the packages a push touches, with the lock's tool versions

**Id:** 671ac5db-2e5e-4cd3-ba80-bd1f4a2d0f4b
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the jour fixe of 2026-11-02 (round jfx-1fze3cfeq55h, request req-qqpvjjhq02jx, adopted by the maintainer: every red CI from formatting or types costs a round of 60 to 90 minutes), card tsk-r37kzg1464b9; the choices below are the author's, in #1405
**Revisit when:** the CLI's dev lock (`cli/requirements/dev.txt`) stops taking the hub's dev pins as constraints (then the hook needs the CLI's tools from an environment of their own), CI lints a package the hook does not know, or most contributors no longer push from a shared machine

`tools/hooks/pre-push` runs `tools/pre_push.py` once a clone sets `git config core.hooksPath tools/hooks`
(CONTRIBUTING.md). For each of `hub/` and `cli/` that the pushed commits touch, it runs CI's own `make lint
typecheck`, without the tests, with the Python of the hub's environment, which `make -C hub install` fills from
the hashed lock. Before that it compares black, ruff and mypy there with the pins in `hub/requirements/dev.txt` and
stops on a difference: the point is the same result as CI, and a local environment drifts (on the machine where the
hook was written, ruff was 0.17.3 against the lock's 0.17.1). It checks the working tree, so it also stops when
HEAD is not the pushed commit or a touched package has uncommitted changes.

**Rejected alternatives:**
- A hook that is on for everyone (installed by a setup step, or a check in CI that it is set): the card asked for
  opt-in, and a contributor without the hub's environment could not push at all.
- The tests in the hook as well: the shared machine's memory limits heavy runs (the entry above), and the tests are
  what CI is for; lint and types are the cheap part.
- A copy of the hook into `.git/hooks`: it would have to be copied again after every change and per clone, and
  `core.hooksPath` with a relative path works in every worktree of the clone. The cost: hooks in `.git/hooks`
  do not run while it is set.
- The tools from wherever `black`/`ruff`/`mypy` are found on PATH: an unpinned version passes or fails other
  code than CI does, which is the round the hook is meant to save.
- The pushed commit checked out into a temporary tree instead of the working tree: mypy needs the environment the
  hub's editable install points at, which is the working tree; checking there and stopping when it differs from
  the push is simpler and says so.
- The CLI's tools from the CLI's own environment: `cli/requirements/dev.txt` is compiled with the hub's dev lock as
  constraints, so its black, ruff and mypy are the versions the hook already compares with; a second environment
  per contributor would check the same versions. (When the hook was written the `cli` CI job installed its dev
  extra unpinned, so there was no lock to compare with.)

## The Keep the Why skill is pinned to the release the context is on, and a check holds every copy to it

**Id:** ac5eadee-18cd-4250-8384-cae3b4459971
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** hardening card tsk-ngx42j6r0jke (the maintainer, 2026-11-04); the scope and the rejected pin chosen by the team lead on the plan, 2026-11-04; `tools/ktw_pin.py`, `AGENTS.md`, `hub/src/maity_hub/config.py`, `hub/src/maity_hub/ktw_skill.py`, `.github/workflows/ktw-lint.yml`
**Revisit when:** a Keep the Why release is adopted (bump every copy with `context-schema`), the skill gains a signed or hashed release format, or the project decides to vendor the skill

The install instructions in `AGENTS.md`, the hub's default
`MAITY_KTW_SKILL_SOURCE` and the Git fallback it derives name the skill's
release tree `tree/v<context-schema>`, not the moving `latest`. The skills
installer is named as `npx skills@<version>`, the version kept once in
`ktw_skill.py` (`SKILLS_INSTALLER`). The linter action is pinned by commit
SHA, its tag in a comment. `-g -y` stays: where the skill lands is
unchanged. `tools/ktw_pin.py`, run in the changelog job of ci.yml, fails
when any copy names another release than `.keep-the-why`'s
`context-schema`, another installer version, or the action by tag. It
reads every form a copy is written in: the full tree URL, a bare
`tree/<ref>`, the hub README's "`<ref>` release tree", and
`skills@<version>` with or without `npx`, each with any ref, so a short
form naming `latest` fails too, as does a `skills` in backticks without a
version. The `.keep-the-why` files of `hub/`, `cli/` and `web/` must exist
and name the root's `context-schema`. That the action's SHA is the
commit of the tag in its comment it cannot check offline: on a bump the
author and the reviewers check it (`git ls-remote` on the tag).

**Reason:** what these lines install is an instruction set every agent in
the project follows, and the installer runs code on the agent's machine.
A moving tag changes both without a change here. `context-schema` already
says which release the context was migrated to, so tying the pins to it
keeps the installed skill and the context on one version. Whoever migrates
the context bumps the pins in the same pull request, and the check names
every line that was missed.

**Rejected alternatives:**
- `pinned-version` with `pinned-path` in `.keep-the-why`: the skill
  supports it only with a vendored copy in the repository. Every agent
  whose installed version differs would then follow that copy, or stop
  hard without it, which changes how every agent works.
- Dropping `-g` to install per project: changes where the skill lands
  for every agent; the pin is about the version only.
- Pins without a check: the next release would be bumped in some copies
  and not others.

## The browser end-to-end test and the join smoke install only from hashed locks, the CLI in an environment of its own

**Id:** 9a0ed6f7-694b-4036-8b78-16ff53aa760a
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** card tsk-3t1tvkd5ktxs (plan approved by the team lead, the reasons below are the author's); `.github/workflows/ci.yml` (`web-e2e`, `join-smoke`), `web/requirements/e2e.in`, `web/Makefile`
**Revisit when:** the CLI gets a hashed dev lock of its own (then that environment can serve), the hub's runtime lock stops constraining Playwright's dependencies (the e2e lock would then need its own environment), or pip installs from a standard lock (`pylock.toml`) without uv

`web-e2e` installs the hub from `hub/requirements/runtime.txt` and `build.txt` and Playwright from
`web/requirements/e2e.txt`, all with hashes, then the hub editable without build isolation.
`e2e.txt` is compiled from `e2e.in` with the hub's runtime lock as constraints (`make -C web lock`),
and `web-e2e` checks it with `make -C web lock-check` first. `join-smoke` installs the hub the same
way, without Playwright. In both jobs the CLI goes into a virtual environment of its own, from
`cli/requirements/release.txt`, editable without build isolation, and only its `maity` is linked
into a directory on `PATH`. Before, `web-e2e` ran `pip install -e hub -e cli playwright==1.64.0`,
and `join-smoke` ran `pip install -e cli`.

**Reason:**
- The hub's and the CLI's editable installs each need their build backend. With build isolation pip
  fetches it for every run without a hash (hatchling with only a lower bound); without it, it comes
  from a hashed lock.
- The CLI's build backend is setuptools, pinned in `cli/requirements/release.txt`, which a lock-check
  holds equal to the CLI's `[build-system]`. That lock is compiled without the hub's pins, so it gets
  an environment of its own rather than meeting the hub's locks in one.
- Only `maity` goes on `PATH`: the CLI environment's own `python` and `pip` would otherwise come
  before the hub's, and the e2e tools run on the hub's Python, where Playwright is.
- With the hub's runtime pins as constraints, a package both locks name (today `typing-extensions`)
  has the same version and hashes in both, so pip installs the three files together.

**Rejected alternatives:**
- setuptools into the hub's environment from the CLI's release lock: two locks compiled apart in
  one environment.
- A lock of its own for setuptools alone: a further lock for one package that the release lock
  already pins and checks.
- `e2e.txt` without the shared packages (`--no-emit-package`): the lock would not stand on its
  own, and pip already accepts the same pin twice.

## The CLI's dev tools come from a hashed lock that takes the hub's dev pins as constraints

**Id:** 3026ae2a-ae3f-43db-8fd3-ced72506d443
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-3t1tvkd5ktxs (plan approved by the team lead, the reasons below are the author's); `cli/requirements/dev.txt`, `cli/Makefile`, `.github/workflows/ci.yml` (`cli`, `cli-windows`), `.github/workflows/release-cli.yml` (`check`)
**Revisit when:** the CLI needs a tool the hub's dev lock pins to a version that does not support the CLI's oldest Python, the CLI gets runtime dependencies, or pip installs from a standard lock (`pylock.toml`) without uv

`cli/requirements/dev.txt` holds the dev extra of `cli/pyproject.toml` with hashes, compiled universally for
Python 3.11 (the CLI's oldest) with `hub/requirements/dev.txt` as constraints (`make -C cli lock`, checked by
`make -C cli lock-check` beside the release lock). CI's `cli` and `cli-windows` jobs, the release workflow's
check job and `make dev` install from it, then the CLI editable without build isolation. Before, they ran
`pip install -e '.[dev]'`, which resolved the newest ruff, black, mypy, pytest, build and wheel on every run.

**Reason:**
- A lint or type result that changes with a tool release nobody chose turns CI red, or green, without a change
  in the repository. On the day this was written the unpinned install got ruff 0.17.4 and mypy 2.4.1.
- With the hub's dev pins as constraints, black, ruff, mypy and pytest are the same versions in both packages.
  The pre-push hook checks both packages with the hub's environment (the entry on the pre-push hook above), so
  it gives the CLI the result CI gives.
- Universal, so one file serves Linux and the Windows job (colorama only where the marker says).
- With the pins that older ruff and mypy brought, `cli/` needed no change: lint and types are clean and the
  tests pass on Python 3.11 from the lock.

**Rejected alternatives:**
- A CLI lock without the hub's constraints: the CLI's tools would drift from the hub's at every `make lock`,
  and the pre-push hook would check the CLI on other versions than CI.
- One lock for both packages: the hub's dev lock is compiled for Python 3.12, the CLI supports 3.11, and the
  hub's lock holds the hub's runtime dependencies, which the CLI must not be tested with.
- Pinning the tools by version in `pyproject.toml`'s dev extra without hashes: the versions would hold, but
  not the files.

## The overlap check before a push decides by merge-tree's exit code, and counts only the conflicts the branch adds

**Id:** 53705871-3016-476f-8482-392106c6f450
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-kpbatay0r79a, from the jour fixe of 2026-11-07 (proposal t5.s1, adopted by the maintainer as req-pcxh3qdmser4); the not-counting rule is the author's and the review of #1462 agreed with it; `tools/overlap.sh`, `tools/test_overlap.py`, `CONTRIBUTING.md` ("The overlap check before a push")
**Revisit when:** git's `merge-tree --write-tree` changes its exit codes, or the team wants a branch to stop for conflicts it does not cause

`tools/overlap.sh` checks a branch against every open pull request that changes one of its files. It
fetches every open pull request's head and takes each one's files from git (`git diff --no-renames
--name-only origin/main...head`), as it takes the branch's own. It three-way merges the branch with each
pull request that shares a file (`git merge-tree --write-tree --no-messages`), and reads only the exit
code: 0 clean, 1 conflict, anything else stops the check with exit 2. For each conflict it runs the same
merge of `origin/main` with that pull request. A file that conflicts there too is named but not counted,
so exit 1 means the branch adds a conflict. Path lists are sorted and compared bytewise (`LC_ALL=C` for
`sort` and `comm`), while git keeps the reader's locale.

Exit 0 says "this branch adds no conflict", which is weaker than "this branch merges cleanly with every
open pull request": a file that already conflicts between `main` and a pull request is not counted,
even when the branch changes how it conflicts there. That pull request's line names the file.

A check that did not run never ends in 0. Every command whose answer the check needs stops it with
exit 2 when it fails: the branch's files or a pull request's (no common history with `main` included,
which would otherwise read as "changes no file"), the list of open pull requests (also when it reaches
`gh`'s limit and may be cut short), the fetch of their heads, a merge, and each comparison of path
lists.

**Reason:**
- The checks the authors wrote by hand grepped git's message for `CONFLICT`. On a machine with a German
  locale git writes `KONFLIKT`, and one check reported a pull request as conflict-free when it was not.
  An exit code is the same in every language. A test runs the check under a German and an English
  locale, and the old grep fails exactly in the German one.
- A merge that git cannot compute (no common history, a missing object) must not read as
  "clean". Every exit other than 0 and 1 stops the check.
- A pull request that already conflicts with `main` is that pull request's to resolve. Counting it
  would make every branch that shares one of its files exit 1, whatever the branch does. The line
  still names it, so the author sees it.
- The files of a pull request come from git, not from `gh pr view --json files`: GitHub's list names a
  renamed file only under its new name, so a pull request renaming a file the branch edits would be
  skipped; its paths are not quoted the way git quotes them, so a path beyond ASCII never matched; and
  it stops at 100 files per pull request (#1431 changes 113, `gh pr view --json files` lists 100).
  With `--no-renames` a rename counts under both names, and `core.quotePath=false` gives one form for
  every list.
- `sort` and `comm` follow the locale's collation, which can order paths differently from bytes and,
  in one review run, made `comm` warn that its input was not sorted. Bytewise order is the same
  everywhere. That warning was not reproduced on the development machine.

**Rejected alternatives:**
- `LC_ALL=C` for the whole script: it would also make git speak English and hide what the exit code
  protects against, and the test for the German case would prove nothing.
- Count every conflict, including those that exist against `main` alone: a branch would stop for
  conflicts it does not cause.
- Leave the check to each author: the jour fixe had just seen it go wrong once.
- Exit 0 only when the branch merges cleanly with every pull request: a pull request's own conflict
  with `main` would stop every branch that touches its files, as with counting every conflict.
- `gh`'s file list per pull request, with a fetch only of those that share a file: fewer fetches, but
  the gaps above, each of which ends in a silent "no overlap".

