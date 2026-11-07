# Completion reports

## `maity report` refuses instead of reporting a partial truth

**Id:** 66da7721-2f51-4105-b82f-4c06cbb9e984
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the refusal on mismatch is from the task brief; re-confirmed by the coordinator after the merged-branch case, 2026-10-22 (a merged head is a forge fact, not an override)
**Revisit when:** the hub's forge probe makes the agent-side check redundant, or agents routinely hit a refusal that is not a real mismatch
**See:** https://github.com/oliver-zehentleitner/maity — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-21
**See:** report.md — f720dd3c-3d21-4e4f-9eb2-3cdb248203ae — as of 2026-10-22
**See:** report.md#without-a-working-gh-the-cards-linked-pull-request-is-read-through-the-hubs-probe — a8ce93bb-51ca-49cb-9782-46f15eaa49e2 — as of 2026-11-07

`maity report` reads the head commit from git, the remote head from
`git ls-remote` on the branch's upstream, and the pull request from `gh`
when gh is installed, and refuses (exit 4) while any of them disagree.
It also refuses on uncommitted changes to tracked files, on a detached
HEAD and on a branch without upstream. When gh is installed but fails —
not logged in, no network — that is an error, not "no pull request";
the pull request is reported as unknown (`pr_status: unknown`, with the
reason) only when gh is not installed or the remote is not on a GitHub
host gh knows. In that case gh is not asked at all, because it could not
answer for that forge. There is no flag to override a refusal.

**Reason:** the claims that went wrong repeatedly in the earlier
multi-agent experiment were "merged", "pushed" and "green", typed by an
agent from memory. A report built from the tools cannot carry a stale
hash, and a report the CLI refuses never reaches the human as a fact.
Treating a failing gh as "no PR" would turn an outage into a false
claim, which is the failure this command exists to prevent. Untracked
files do not refuse, since scratch files are common and never part of
what is reported.

**Rejected alternatives:**
- Report whatever is known and mark the disagreeing fields as
  unverified: leaves the judgement to the reader, who is exactly the
  person the report should spare from checking.
- A `--force` flag: the first stuck agent would use it, and the report
  would look as trustworthy as a verified one.

## A merged pull request's head stands in for a deleted branch

**Id:** f720dd3c-3d21-4e4f-9eb2-3cdb248203ae
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** a peer agent's report that `maity report` was refused after its pull request was merged and the branch deleted, and the coordinator's card with the options, 2026-10-22
**See:** report.md — 66da7721-2f51-4105-b82f-4c06cbb9e984 — as of 2026-10-22
**Revisit when:** the forge tool can no longer find a pull request by a deleted branch's name, or reports from merged heads are wanted for branches without a pull request

When the branch's upstream no longer exists on the remote, `gh` finds a
pull request for that branch, it is merged, and its head equals the local
HEAD, `maity report` takes the head as `remote_head` and reports. Any
other deleted branch is still refused, with a message naming push, the
merged case and `--no-code`.

**Reason:** after a merge with branch deletion the forge still holds the
reported commit, as the merged pull request's head, so nothing in the
report is unverified. The hub's probe already treats a branch it no
longer has as no mismatch and compares only the pull request head. The
pull request is found by branch name without extra input, so no new
flag can be misused to report a head nobody pushed.

**Rejected alternatives:**
- A `--pr N` flag naming the pull request: an agent could name a merged
  pull request with another head, and the CLI would have to check it
  against the same facts it can find by itself.
- Only a clearer refusal: it would leave agents that report after a
  merge with no correct way to report code at all.

## The why of a code report is checked locally, against the last resume

**Id:** a99c8924-66bc-4d9f-b9f9-590c6276546b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §6.23 and the §13 rows (contract #390: a code report without `--why`/`--no-why` refused locally under `required`, naming the two flags; the CLI never confirms on its own); the coordinator's card for the CLI side, 2026-10-25
**Revisit when:** the hub exposes the policy without a resume, or a report has to be sent while the last resume is out of date with a policy change

`maity resume` stores whether the packet's `keep_the_why.commitment` is
`required`. `maity report` reads that value and refuses a code report
that has neither `--why` nor `--no-why` (exit 4) before git, gh or the
hub are asked. Both flags are checked for the shape the hub accepts
(`<path>.md#<id>` relative to the root; a reason of 10 characters or
more), and `--no-code` refuses them. The `Keep the Why` block names
`maity ack keep-the-why` literally rather than the packet's `ack`
field, and the CLI sends the confirmation only when the agent runs the
command.

**Reason:** a refusal from the hub would come only after the git facts
and the pull request were read. With the flags named locally, the agent
gets the rule at the moment it writes the report. A stored flag can be
out of date when the policy changes between resumes. The hub still
decides: a stale `false` means the hub answers `invalid` (`required`).
A stale `true` refuses a report the hub would have taken, and only
until the next resume. A command taken from the packet would be
something the CLI prints for an agent to run, so the CLI names it
itself.

**Rejected alternatives:**
- Asking the hub for the policy before every report: one more call per
  report, for a value the packet already carried.
- Leaving the check to the hub alone: correct, but the agent learns the
  rule from a field code after the git checks, not from the command.

## A report is checked against the card's pull request, without a flag to name one

**Id:** 8c58cebb-b7e1-4947-8776-8f5bcb6c566c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** a member's report that `maity report` for a merged pull request, sent from the branch of the next one, filed the wrong head and pull request on the card (2026-10-30); the coordinator's decision on the card tsk-scw537kndwwg between a `--pr` flag and a card check, and to refuse a checkout without a found pull request, 2026-10-31; the contract text of §6.6 in PR #816
**See:** report.md — f720dd3c-3d21-4e4f-9eb2-3cdb248203ae — as of 2026-10-31
**Revisit when:** reports for a pull request other than the checked-out one become routine, or cards carry no pull request link and no earlier report often enough that the check never applies
**See:** report.md#without-a-working-gh-the-cards-linked-pull-request-is-read-through-the-hubs-probe — a8ce93bb-51ca-49cb-9782-46f15eaa49e2 — as of 2026-11-07

Before sending, `maity report` prints the branch, head and pull request it
reports, and reads the card. It refuses (exit 4) when the card links pull
requests (`kind: pr`, in the same repository) and the one found for the
checkout is not among them, or when the card's last report names another
pull request that the probe has not seen merged or closed. The message
names the way out: check out that pull request's branch, or its merged
head after a merge with the branch deleted, and report from there. A
report with `--no-code` reads no card.

**Reason:** the facts were right for the checkout and wrong for the card:
nothing in the report was typed, it described another pull request. The
card itself says which pull request it belongs to, once it is linked or
reported, so the check needs no new input and keeps every fact coming
from git and the forge. A merged or closed earlier pull request does not
refuse, since a follow-up pull request on the same card is legitimate.
A checkout without a found pull request (`pr_status` `none`, or `unknown`
because gh is missing or the remote is not on a host gh knows) is refused
on a card with pull request links as well, rather than let through: the
check exists to show that the report describes the card's pull request,
and a report that cannot name one cannot show that. Letting it through
would file the checkout's facts on the card exactly in the case the check
cannot see, the same partial truth 66da7721 refuses; the message says
which of the two it is, and the way out is the card's branch, or gh, or
`--no-code` when the report carries no code. An open pull request of the
last report in another repository of the owner does not refuse either,
as a link there does not: it says nothing about this checkout.

**Rejected alternatives:**
- A `--pr N` flag that reads head, branch and state of that pull request
  from the forge instead of the checkout: the forge facts would be true,
  but for whichever pull request the agent names, so a mistyped number
  files a wrong pull request with verified-looking facts. That is the
  risk f720dd3c rejected a `--pr` flag for, in another form, and the
  card check covers the case without a flag.
- Only printing the reported branch and pull request: it helps an agent
  that reads it, and the agent that made the mistake had no reason to.
- Letting a checkout without a found pull request through, and checking
  only a pull request that was found: a missing gh, or a branch whose
  pull request is not open yet, would then skip the check on a linked
  card, and the report would file that checkout's head as the card's
  work unchecked. The refusal costs a reachable fix (the card's branch,
  or installing gh); a wrong report on the card costs a reviewer's time.

## What maity hands to git and gh is checked first, and git's transports are fixed

**Id:** 4f4e8ada-9e3b-47bc-8a9e-d44daf025512
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** CLI hardening task, plan approved by the coordinator, 2026-11-04; verified with git 2.43 (a clone's own `protocol.<name>.allow` outranks `-c protocol.allow` on the command line, `GIT_ALLOW_PROTOCOL` outranks both; `ls-remote --heads -- <remote> <ref>` keeps both as operands)
**See:** report.md#maity-report-refuses-instead-of-reporting-a-partial-truth — 66da7721-2f51-4105-b82f-4c06cbb9e984 — as of 2026-11-04
**See:** runner.md#sandboxed-agents-git-redirects-are-pinned-other-clones-and-secrets-unreadable — ea36c196-f8e6-43ae-bc47-49c8d5379a65 — as of 2026-11-04
**Revisit when:** maity checks a clone's configuration before its own git, git changes how `GIT_ALLOW_PROTOCOL` ranks against configuration, a forge reached over another transport is supported, or `report` learns a forge other than GitHub

`maity report` reads a branch's upstream from the clone's configuration
and passes it to `git ls-remote`. Before that, the remote, every URL it
is configured with and the merge ref are checked: none may start with
`-` or contain `::`, and the merge ref must lie under `refs/heads/`.
Every other upstream `git push -u` stores still reads: a configured
remote whatever its name, a URL, a relative path, `host:path`. A refused
one gets the hint to set the upstream with `git push -u`. `ls-remote`
gets `--` before them. Every git run through `proc.run` (maity's own
git, such as report, checkpoint, the cite and text checks, the state
lookup, the join's root lookup, the first resume's remote check and the
build identity) gets `GIT_ALLOW_PROTOCOL` with `https`, `http`,
`ssh`, `git` and `file`; the runner's direct clone of a workspace passes
its own `https:ssh`, because the variable replaces its `-c protocol.*`
settings as well. A `GIT_ALLOW_PROTOCOL` already in the environment, the
operator's own, narrows that list and is never widened by it. Programs `proc.run` starts by name come from an absolute
PATH entry, never the current directory (a name with a directory in it
is a path the caller chose and is used as given), and on Windows
with `NoDefaultCurrentDirectoryInExePath` set for what they start in
turn. Two runner paths run git without `proc.run` and keep their own
settings: `gc`'s read of a clone (`operate.unsaved_work`, pinned
`protocol.allow=never` and a cleaned environment) and a workspace clone
made as the agents' user (`as_user.run`, the `-c` list of `https` and
`ssh`). Settings in the clone's own configuration still apply to
`ls-remote`; this change does not limit them. Under the runner, a
companion change that lands together with this one runs git only after
the clone passes the plain-clone check `gc` uses.
`gh pr view` is asked only about an `https` URL on github.com or
`GH_HOST`, the same hosts `report` already asks gh about.

**Reason:** the clone's configuration is written by the agent working in
it, so it is input, not maity's own setting. maity only reads a remote;
a value git reads as an option, or a remote helper
(`<transport>::<address>`), would change what git runs for that. The transports are fixed through the
environment because a command-line `-c protocol.allow=never` loses to a
`protocol.<name>.allow` in that same configuration. The value checks
stay as a second line beside it, and they give a refusal that names the
fix instead of git's error. Windows searches the current directory
before PATH for a bare program name.

**Rejected alternatives:**
- `-c protocol.allow=never` plus one `always` per wanted transport on
  git's command line: tried first; a clone's own
  `protocol.ext.allow=always` still applies, since a protocol's own key
  outranks the default.
- Only `--` before the operands: covers a leading `-`, not a remote
  helper in the remote's name or URL.
- Accepting only remote names in ASCII and URLs of a few known shapes:
  refused upstreams `git push -u` makes (a remote named in another
  script, `../remote.git`, an ssh alias as `host:path`), and the
  transports are limited by the environment anyway.
- `shutil.which`: on Windows it searches the current directory first.

## Without a working gh, the card's linked pull request is read through the hub's probe

**Id:** a8ce93bb-51ca-49cb-9782-46f15eaa49e2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-grk7tg5temyc, from two Claude Code cloud sessions whose `gh` was missing or got HTTP 403 on GraphQL, so their reports were refused on linked cards (2026-11-07); the lead's go on the plan (Maity message, 2026-11-07); docs/api.md §11 (`GET /probe?pr=N&max_age=0`)
**See:** report.md#maity-report-refuses-instead-of-reporting-a-partial-truth — 66da7721-2f51-4105-b82f-4c06cbb9e984 — as of 2026-11-07
**See:** report.md#a-report-is-checked-against-the-cards-pull-request-without-a-flag-to-name-one — 8c58cebb-b7e1-4947-8776-8f5bcb6c566c — as of 2026-11-07
**See:** report.md#a-merged-pull-requests-head-stands-in-for-a-deleted-branch — f720dd3c-3d21-4e4f-9eb2-3cdb248203ae — as of 2026-11-07
**Revisit when:** the probe's pull request read gains or loses `head_sha`, gh works in cloud sessions again, or a report should name a pull request the card does not link

When gh is missing, or is installed and fails (`gitfacts.collect` keeps that
failure as `forge_error` instead of raising it), `maity report` reads the card
and asks the hub's probe about each pull request the card links in the
project's repository, at most five (more are named in one line and not read),
with `max_age=0`; the hub may still answer from a read up to 30 seconds old
(`FORCED_FLOOR`, §11.4), and a head that is that stale refuses, never files
another commit. A pull request whose
`head_sha` equals what `git ls-remote` answered for the branch, compared whole,
is reported as `pr_status: found` with number, URL, head and state from the
probe, and the terminal line says it was read by the hub's probe. Linked pull
requests with another head refuse (exit 4), naming each head and the branch's.
A probe that is not configured, unavailable or finds nothing changes nothing:
the report goes on as before, refused on a linked card as 8c58cebb says, and a
gh that failed is raised as the error it was, as 66da7721 says.

A branch deleted after its merge is the same case without a remote head: where
f720dd3c asks gh for the merged pull request by the branch's name, the report
asks the probe about the card's linked pull requests and takes one that is
`merged` with `head_sha` equal to the local HEAD as the branch's stand-in
(`remote_head` the merged head). A linked pull request in another state or with
another head refuses; without a linked pull request the branch counts as
missing, as before. This runs only when the local check would refuse, and a
card that cannot be read leaves that refusal as it is.

What decides here is the hub's record that the card links the pull request, and
the probe's read of it, not a GitHub lookup by the branch's name. A link is
added by a member and observed by the hub (§6.13); the head must still equal
what git has, so a wrong link can only refuse, never file another commit.

**Reason:** in cloud sessions gh is often missing or cannot use GraphQL, and the
card then stayed `in_progress` with nothing wrong in the work. The probe is the
hub's own forge read, with the operator's or the owner's grant and of the
project's repository only, so the pull request still comes from the forge, not
from the agent; asking only about pull requests the card links keeps the
choice out of the agent's hands, and the exact head match keeps the report tied
to what git pushed. Both earlier entries name this as their revisit trigger;
re-checked on 2026-11-07, both stay active: this entry extends them (a forge
read when gh cannot answer), it replaces neither the refusal on a mismatch nor
the check against the card's pull request.

**Rejected alternatives:**
- A `--pr N` flag: 8c58cebb rejected it, and the probe makes it no safer, since
  the number would still be the agent's.
- The hub's cached observation of the link: a pull request link's `observed`
  carries no head (§6.13), and a cached read may be older than the push.
- gh's REST API as a fallback for gh's GraphQL: helps only where gh is
  installed and logged in, not where it is missing.
- Reporting `pr_status: unknown` on a linked card: that is the partial truth
  66da7721 and 8c58cebb refuse.
