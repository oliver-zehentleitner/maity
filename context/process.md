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
