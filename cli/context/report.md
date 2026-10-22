# Completion reports

## `maity report` refuses instead of reporting a partial truth

**Id:** 66da7721-2f51-4105-b82f-4c06cbb9e984
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** CLI skeleton design, 2026-10-21; the refusal on mismatch is from the task brief
**Revisit when:** the hub's forge probe makes the agent-side check redundant, or agents routinely hit a refusal that is not a real mismatch
**See:** https://github.com/oliver-zehentleitner/maity — 098ef90f-83b8-4b38-9c21-1e89c086b6db — as of 2026-10-21

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
