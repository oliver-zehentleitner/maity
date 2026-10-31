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
