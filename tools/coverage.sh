#!/usr/bin/env bash
# The coverage check before a MERGE-READY: does the main that a pull request's green ci-ok run
# tested contain every main commit on the pull request's files since its merge base?
#
#   tools/coverage.sh <pr>
#
# A pull request's CI runs on its merge with main as main was when the run started. A commit that
# reaches main later and touches the same files is in neither that run nor the review, even when
# `git merge-tree` of main with the head is clean today (it prints only a tree id). This check
# names such commits.
#
# Steps, all reads (GitHub REST GETs through `gh api`, and `git fetch` into local refs only; no
# push, no merge, no CI re-run):
# 1. The pull request (`GET pulls/<pr>`): open, and based on main. A pull request stacked on
#    another branch is not handled and says so.
# 2. `git fetch` of origin's main and the pull request's head, which must be the head GitHub
#    names.
# 3. The ci-ok run: the newest `pull_request` run of .github/workflows/ci.yml for exactly that
#    head and branch, as tools/ci_watch.py picks it. It must be completed with the `ci-ok` job
#    green; anything else ends the check (exit 2), since there is no green run to judge.
# 4. The main it tested: the run object does not say, but actions/checkout logs
#    `HEAD is now at <sha> Merge <head> into <main>` in each job that checks out. The first such
#    job log of the run's attempt is read; its <head> must be the pull request's head, and its
#    <main> must be on origin/main. Logs expire with GitHub's retention; then the check says so.
# 5. The pull request's files (`git diff --no-renames <merge base> <head>`, so a rename counts
#    under both names) and the main commits on them since the merge base (`git rev-list
#    --no-merges --full-history`). Each is covered when it is an ancestor of the tested main.
#
# Exit 0 when every such commit is covered, 1 when at least one is not (merge origin/main into
# the branch and push: a re-run of the old run tests the same merge again), 2 when the check
# could not run. Every command whose answer it needs stops the check when it fails, so a check
# that did not run never ends in 0. It does not judge whether a main change matters, and it does
# not replace the review lead's merge-base and merge-tree check before a merge.
set -uo pipefail

WORKFLOW=.github/workflows/ci.yml
SUMMARY_JOB=ci-ok

die() {
  echo "coverage: $*" >&2
  exit 2
}

# Paths as git stores them, not quoted octal, and every path taken literally (a file named `:x`
# is no pathspec magic).
git() {
  GIT_LITERAL_PATHSPECS=1 command git -c core.quotePath=false "$@"
}

[ "${BASH_VERSINFO[0]}" -ge 4 ] || die "needs bash 4 or newer"
command -v gh >/dev/null || die "needs the gh CLI"
[ $# -eq 1 ] && [[ $1 =~ ^[1-9][0-9]{0,8}$ ]] || die "usage: tools/coverage.sh <pull request number>"
pr=$1

# Origin's owner, name and host, read as tools/overlap.sh reads them (see there for why gh's own
# choice of repository and host is never taken).
origin=$(git config --get remote.origin.url) || die "no remote origin"
slug=${origin%/}
slug=${slug%.git}
slug=${slug//:/\/}
[[ $slug == */*/* || $slug == [!/]*/* ]] || die "cannot read an owner and a repository from origin's URL $origin"
repo_name=${slug##*/}
slug=${slug%/*}
repo_owner=${slug##*/}
[[ $repo_owner =~ ^[A-Za-z0-9._-]+$ && $repo_name =~ ^[A-Za-z0-9._-]+$ ]] \
  || die "cannot read an owner and a repository from origin's URL $origin"
case $origin in
  file://*) authority="" ;;
  *://*)
    authority=${origin#*://}
    authority=${authority%%/*}
    ;;
  */*:* | *:*) authority=${origin%%:*} ;;
  *) authority="" ;;
esac
[[ $origin == *://* || $authority != */* ]] || authority=""
authority=${authority##*@}
case $authority in
  \[*) repo_host=${authority%%]*}] ;;
  *) repo_host=${authority%%:*} ;;
esac
repo_host=${repo_host,,}
if [[ $repo_host == localhost || $repo_host == "[::1]" || $repo_host =~ ^127(\.[0-9]{1,3}){3}$ ]]; then
  repo_host=github.com
fi
[[ $repo_host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
  || die "cannot read a host from origin's URL $origin"
repo="repos/$repo_owner/$repo_name"

api() {
  gh api --hostname "$repo_host" -H "Accept: application/vnd.github+json" "$@"
}

# 1. The pull request.
info=$(api "$repo/pulls/$pr" --jq '"\(.state) \(.merged) \(.head.sha) \(.base.ref) \(.head.ref)"') \
  || die "reading pull request #$pr of $repo_owner/$repo_name on $repo_host failed (gh api)"
[[ $info =~ ^(open|closed)\ (true|false)\ ([0-9a-f]{40})\ ([^\ ]+)\ ([^\ ]+)$ ]] \
  || die "unexpected answer for pull request #$pr: $info"
state=${BASH_REMATCH[1]}
merged=${BASH_REMATCH[2]}
head=${BASH_REMATCH[3]}
base_ref=${BASH_REMATCH[4]}
head_ref=${BASH_REMATCH[5]}
if [ "$state" != open ]; then
  [ "$merged" = true ] && die "#$pr is merged; nothing to check"
  die "#$pr is closed; nothing to check"
fi
[ "$base_ref" = main ] \
  || die "#$pr is stacked on $base_ref, not main; coverage.sh does not handle stacked pull requests"

# 2. Main and the head, under a ref of this run only.
tmp="refs/maity-coverage/$$"
trap 'git update-ref -d "$tmp" 2>/dev/null' EXIT
git fetch --quiet --no-tags origin main "+refs/pull/$pr/head:$tmp" \
  || die "git fetch of origin's main and #$pr's head failed"
main=$(git rev-parse --verify --quiet "refs/remotes/origin/main^{commit}") \
  || main=$(git rev-parse --verify --quiet "FETCH_HEAD^{commit}") \
  || die "no origin/main after the fetch"
fetched=$(git rev-parse --verify --quiet "$tmp^{commit}") || die "no fetched head of #$pr"
[ "$fetched" = "$head" ] || die "#$pr is at $head on GitHub but at $fetched on origin; run again"

# 3. The newest ci run for exactly this head and branch.
runs=$(api "$repo/actions/runs?head_sha=$head&event=pull_request&per_page=100" \
  --jq '.workflow_runs[] | "\(.created_at) \(.id) \(.run_attempt) \(.status) \(.conclusion) \(.path) \(.head_branch)"') \
  || die "listing the ci runs of $head failed (gh api)"
matching=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  [[ $line =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\ [0-9]+\ [0-9]+\ [a-z_]+\ [a-z_]+\ [^\ ]+\ [^\ ]+$ ]] \
    || die "unexpected line in the list of ci runs: $line"
  read -r _ _ _ _ _ path branch <<<"$line"
  [ "$path" = "$WORKFLOW" ] && [ "$branch" = "$head_ref" ] && matching+=("$line")
done <<<"$runs"
# Newest by start time, then by id: the same order as tools/ci_watch.py. Sorted bytewise, since a
# locale's collation may skip the punctuation of a timestamp.
newest=""
[ "${#matching[@]}" -eq 0 ] \
  || newest=$(printf '%s\n' "${matching[@]}" | LC_ALL=C sort -k1,1 -k2,2n | tail -n 1)
[ -n "$newest" ] || die "no ci run for #$pr at $head yet"
read -r _ run_id attempt status _ _ _ <<<"$newest"
run_url="https://$repo_host/$repo_owner/$repo_name/actions/runs/$run_id"
[ "$status" = completed ] || die "the newest ci run for $head is still $status: $run_url"

jobs=$(api "$repo/actions/runs/$run_id/attempts/$attempt/jobs?per_page=100" \
  --jq '.jobs[] | "\(.id) \(.conclusion) \(.name)"') \
  || die "listing the jobs of run $run_id failed (gh api)"
summary=""
job_ids=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  [[ $line =~ ^([0-9]+)\ ([a-z_]+)\ (.+)$ ]] || die "unexpected line in the list of jobs: $line"
  [ "${BASH_REMATCH[3]}" = "$SUMMARY_JOB" ] && summary=${BASH_REMATCH[2]}
  # A skipped job checked nothing out and has no log.
  [ "${BASH_REMATCH[2]}" = skipped ] || job_ids+=("${BASH_REMATCH[1]}")
done <<<"$jobs"
[ -n "$summary" ] || die "run $run_id has no $SUMMARY_JOB job: $run_url"
[ "$summary" = success ] || die "$SUMMARY_JOB is $summary in the newest ci run for $head: $run_url"

# 4. The main the run tested, from actions/checkout's log line.
tested=""
for job in ${job_ids[@]+"${job_ids[@]}"}; do
  log=$(api "$repo/actions/jobs/$job/logs") || die "reading the log of job $job failed (gh api); GitHub may have expired it"
  merges=$(grep -oE 'HEAD is now at [0-9a-f]+ Merge [0-9a-f]{40} into [0-9a-f]{40}' <<<"$log" | sort -u)
  [ -n "$merges" ] || continue
  [ "$(wc -l <<<"$merges")" -eq 1 ] || die "job $job's log names more than one merge: $merges"
  merged_head=$(cut -d' ' -f7 <<<"$merges")
  tested=$(cut -d' ' -f9 <<<"$merges")
  [ "$merged_head" = "$head" ] \
    || die "run $run_id tested a merge of $merged_head, not of #$pr's head $head: $run_url"
  break
done
[ -n "$tested" ] || die "no job log of run $run_id names the merge it tested: $run_url"
git cat-file -e "$tested^{commit}" 2>/dev/null || die "the tested main $tested is not in this clone"
git merge-base --is-ancestor "$tested" "$main"
case $? in
  0) ;;
  1) die "the tested main $tested is not on origin/main" ;;
  *) die "git merge-base --is-ancestor $tested $main failed" ;;
esac

# 5. The pull request's files and the main commits on them since the merge base.
base=$(git merge-base "$main" "$head") || die "no merge base of origin/main and $head"
files=$(git diff --no-renames --name-only "$base" "$head") || die "git diff $base $head failed"
mapfile -t paths < <(printf '%s\n' "$files" | sed '/^$/d')
echo "coverage: #$pr at $head; $SUMMARY_JOB green in $run_url"
echo "coverage: that run tested the merge with main $tested; merge base $base"
if [ "${#paths[@]}" -eq 0 ]; then
  echo "coverage: #$pr changes no file against its merge base"
  exit 0
fi
commits=$(git rev-list --no-merges --full-history "$main" "^$base" -- "${paths[@]}") \
  || die "git rev-list of main's commits on #$pr's files failed"
total=0
missing=0
while IFS= read -r commit; do
  [ -n "$commit" ] || continue
  total=$((total + 1))
  git merge-base --is-ancestor "$commit" "$tested"
  case $? in
    0) continue ;;
    1) ;;
    *) die "git merge-base --is-ancestor $commit $tested failed" ;;
  esac
  missing=$((missing + 1))
  subject=$(git log -1 --format=%s "$commit") || die "git log $commit failed"
  touched=$(git diff-tree --no-commit-id --name-only --no-renames -r "$commit" -- "${paths[@]}") \
    || die "git diff-tree $commit failed"
  echo "  $commit $subject [${touched//$'\n'/,}]"
done <<<"$commits"

# For information only: merge-tree of today's main with the head prints a tree id and nothing
# about which main commits a run has seen.
tree=$(git merge-tree --write-tree --no-messages "$main" "$head" 2>/dev/null | head -1)
echo "coverage: merge-tree of origin/main with the head today: exit ${PIPESTATUS[0]}, tree ${tree:-none}"

if [ "$missing" -gt 0 ]; then
  echo "coverage: $missing of $total main commits on #$pr's files since the merge base are not in the tested main;" \
    "merge origin/main into the branch and push for a new $SUMMARY_JOB run (a re-run tests the old merge again)"
  exit 1
fi
echo "coverage: all $total main commits on #$pr's files since the merge base are in the tested main"
exit 0
