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
