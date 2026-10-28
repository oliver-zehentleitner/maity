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

## Multi-agent review runs exhausted the maintainer's monthly budget

**Id:** 1a5e729f-816a-4682-ab8c-a2029aa1ea0a
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

Two review runs — three dimensions per pull request, an independent
verifier per finding — used several million tokens each; the day's
background agents used roughly twenty million. The second run hit the
maintainer's monthly spend limit, and 54 verifiers stopped mid-way, so
part of the findings were judged rather than reproduced. Reviews were
switched to one reviewer per pull request that reproduces its own
blocker and should-fix findings, plus a targeted re-check by the
coordinator: about 150 thousand tokens per review, and the reviews kept
finding real defects (two of them blockers in the release gate).

**Learned:** the token budget is a shared, binding constraint, as it was
in the earlier seven-agent project. Maity records the model on every
event so that cost per role and per kind of work can be compared later;
a budget the admin roles can see, and review depth as a project policy
rather than a habit, are the follow-ups.

## One agent stopped another's server: process clean-up by pattern

**Id:** 871f9226-a39d-4a71-84a6-c0b65a4fbf2e
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

An agent ended its own test server with `pkill -f "maity-hub serve"`. The
pattern also matched the dogfood hub the maintainer was about to use,
and a leftover server of an earlier review that had held port 8080 for
hours. The agent reported it at once and precisely; the hub was
restarted without data loss. The leftover had already forced the
dogfood hub onto another port.

**Learned:** on a shared machine a process belongs to whoever started
it. The rule for every agent since: start servers in the background,
keep the PID, kill exactly that PID, never by pattern, and treat the
dogfood hub's port as off limits. For Maity this belongs in the rules a
project serves to its agents, and the dogfood hub's address is project
knowledge every agent receives at join.

## The contract contradicted itself, and an implementation took one side

**Id:** a693f08e-ee64-44b7-b245-872065c2dc0e
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21; reviews of pull requests #21 and #30

Two review blockers came from the API contract, not from the code. The
PATCH rule for cards named holder, creator and admin, while the scope
table gave reviewers the right to close a reviewed card; the hub
implemented the narrower rule, so under the default organisation preset
the reviewer could never close anything. And "release groups among the
shipped cards" was implemented literally, so a paired card left out of
a release was ignored — the half-merged pair the release gate exists
for. Each implementation also listed its own readings of open points,
and most of the contract's later amendments came from those lists.

**Learned:** a written contract with one owner works only if ambiguity
surfaces before the code. The habit that worked: every slice lists the
readings it chose, the contract owner decides each in the document
before the merge, and reviews check the contract against itself as well
as the code against the contract. Maity's contract cards (one arbiter,
proposed then final) are the product form of this.

## Checks that passed while the thing they checked did not work

**Id:** 5ce3c8ac-2db5-4a49-8934-65c6bc790496
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

Several checks were green while the behaviour they named was broken. A
pull request description claimed a clean lint run because the output
went through `tail` and the exit code was never read. The dashboard was
built and reviewed against fixtures, and the first real login found
that a new account could not create a project at all. A smoke test's
"the join page never shows the code" line was a negated command, which
`set -e` ignores, so it could never fail; another of its lines broke
whenever a random token started with a hyphen. The operator command the
maintainer was given lacked two required arguments, because the
instruction had not been run.

**Learned:** a claim is only as good as the run behind it: exit codes
read, the real system instead of a stand-in, every instruction executed
before it is handed to a person. Maity's completion report takes its
facts from git and the forge rather than from what an agent types, and
dogfooding started as soon as an agent could join, precisely because
fixtures had hidden the first real defect.

## Platforms changed underneath the build

**Id:** f3bec014-28b7-4bfe-9ca8-304f1481fceb
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21; the coordinator's observations, 2026-10-22
**Revisit when:** push or pull request events stop triggering workflows again

Two external changes broke checks that had nothing to do with the code.
A release of the Keep the Why linter moved its rolling action tag before
the package was on PyPI, so every project's linter job failed for
several minutes. And from a certain merge on, the forge stopped creating
push events for merges into `main`: pull request runs went on, but no
workflow ran on `main` and the project site was not deployed, with the
platform's status page reporting everything operational.

On 2026-10-22 push runs on `main` came back (CI, pages and audit ran on
the merges again), so the site is deployed by its workflow again and the
manual deploy has ended. The cause stays unexplained and lies on the
forge's side. The same day showed more of it: jobs left `in_progress` on
runs that had completed, and pull requests that started no CI at all;
closing and reopening such a pull request triggered the runs.

**Learned:** a green pull request is not a deployed main branch. Maity's
read-only forge probe observes what actually ran, and "the default
branch's checks are green and the site is live" belongs on the release
checklist as an observed item, not an assumption.

## Messages crossed, and a review ran against a stale head

**Id:** f5af51a7-1a53-4782-9af5-6c91b4f7d77c
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-21

Two instructions to the dashboard's agent crossed: "apply the contract's
renames" arrived first, "change nothing until the review is in" second.
The agent had already done the first, held it locally, and the review
ran against the old pushed head — half of its findings were renames that
were already done. The coordinator then filtered the review by hand.

**Learned:** an instruction about a moving branch has to name the state
it refers to, and a review has to name the head it reviewed. Maity's
completion report carries the head from git, and reviews of a card
should be tied to the head they saw, so that a crossing like this shows
instead of costing a review.

## Agents worked for hours without Keep the Why: the instruction to load it was never read

**Id:** c0692bcc-f883-443e-a55c-e280a117cd9d
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-27; the coordinator's own session and the agents' answers to a check the same day
**See:** projects.md#maity-tells-every-agent-how-to-load-keep-the-why-and-lets-it-adopt-the-projects-personal-defaults — 4859417a-15f0-44c1-821e-cc80f888e34d — as of 2026-10-27

On the day a new team joined, the coordinator and at least one coding
agent worked for hours without the Keep the Why skill loaded. The
instruction to load it first lives in `AGENTS.md`. Claude Code reads
`CLAUDE.md`, and the root `CLAUDE.md` is a personal, ignored file, so a
clone without one never shows the instruction. The coordinator's
session had also started outside its clone, its machine had neither the
skill nor `npx`, and the hub did not enforce Keep the Why: the
project's flag read false, although it had been ticked at creation, and
the commitment of the contract was not built. The agents wrote
`context/` entries anyway, from the format they saw in the repository,
but without the skill's setup check, its linter run or its rules.

**Learned:** an instruction that lives in one file is only as good as
every agent's way of reading that file. The contract now says Maity
hands the skill's install and load instructions to every agent in its
resume (§6.23, decided the same day). As of this entry the hub does not
do it yet: its resume still carries only `enabled` and `instruction`.
Until that is built and verified on the live hub, each Claude Code
agent keeps a local `CLAUDE.md` that imports `AGENTS.md`, and loads the
skill as `AGENTS.md` says.

**Rejected alternative:** commit a root `CLAUDE.md` with `@AGENTS.md`.
The ignore file marks it as personal, so committing it would override
every developer's own file. That it is meant to be personal is read
from the ignore file's comment, not confirmed by the maintainer.

## Parallel full test suites on the shared VM took it down twice

**Id:** 998fc76e-6c7b-4791-91de-d04a0d514333
**Type:** incident
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's notice of 2026-10-23, after two outages of the shared VM that also killed the agents' wait loops and a full-suite run
**Revisit when:** the agents get hosts of their own, or the VM's memory is sized for parallel suites
**See:** incidents.md#the-shared-machine-ran-out-of-disk-review-artefacts-filled-it — b1c7bd7d-a497-41ed-97e3-989f63c80a1c — as of 2026-10-27

The shared VM went down twice, and one agent's `maity wait` and its
local full-suite run died with it. The coordinator named memory pressure
from several agents running full test suites in parallel as the prime
suspect; that was not confirmed. The rule since then: no local
full-suite runs on the VM, only one targeted test file at a time, and
CI runs the full suite on all three databases.

**Learned:** like the full disk, a shared host is a shared resource that
parallel work can exhaust; the cause stays inferred, the rule is stated.
After a reboot every agent re-arms exactly one wait.

## Messages lost their code spans: the shell ran them before `maity` saw the text

**Id:** 5f1597e2-a1d2-416b-af05-44b60854533a
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** project messages of 2026-10-27 (the root cause found by an agent, seq 6523; a message that arrived as `-`, seq 6534 and its resend 6536); build session, 2026-10-27

Agents wrote messages as `maity say <to> "… `code` …"`. Inside double
quotes the shell runs backtick spans and `$(…)` as command substitution
before `maity` starts, so the messages arrived with holes where the code
was, and the sender saw nothing wrong. Two more slips of the same kind
followed on the same day. The coordinator sent `-` to read a message
from standard input, a CLI feature that was still in review, so the
installed CLI sent the single character `-`. An agent writing a file
through a shell heredoc had an inner `<<'EOF'` example end the outer
heredoc early.

**Learned:** text with code goes to a command through a file or a quoted
heredoc with a delimiter it cannot contain, never inline in double
quotes. With the installed CLI that means a quoted heredoc into a shell
variable that is then passed quoted. The remediation in the CLI is in
review (PR #435): free text from standard input (`-`) and files, a
warning for inline text that looks eaten, and the safe form in the
pointer block, the skill and `docs/agents.md`. Agents can use it only
once a CLI with it is released to the index they install from.
Instructions must not use a flag ahead of that release.

## A rejoined identity on a new machine replayed thousands of old events

**Id:** 48327066-0929-495b-8f2c-e85f55b0878c
**Type:** incident
**Status:** active
**Evidence:** confirmed
**Source:** build session, 2026-10-27; the coordinator's welcome message of the same day, which reported the same at its own join

An agent identity that had worked on another machine joined again on a
new one with a fresh clone. Its `maity wait` started at the event cursor
of the identity's earlier sessions, days old, so it first returned events
from the 22nd: requests long answered and pull requests long merged. The
agent checked the first one against GitHub, found it merged, and then
drained about 5000 events in batches to reach the present. The
coordinator's own fresh instance started at seq 115 of more than 6300
the same day. The join output itself was about 50 KB, mostly that
backlog.

**Learned:** for a new instance the old cursor mostly holds history,
and an agent that does not recognise it as such acts on stale
instructions. Whether a fresh instance should start near the present
with a short summary, and how long a join output may be, is not
decided; it was raised with the coordinator as a possible card.
