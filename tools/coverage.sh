#!/usr/bin/env bash
# The coverage check before a MERGE-READY: does the main that a pull request's green ci-ok run
# tested contain every main commit that changes one of the pull request's files?
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
# 2. `git fetch` of origin's main and the pull request's head, each into a ref of this run (never
#    a tracking ref the fetch may leave alone); the head must be the one GitHub names. A shallow
#    clone is refused.
# 3. The ci-ok run: the newest `pull_request` run of .github/workflows/ci.yml for exactly that
#    head and branch, as tools/ci_watch.py picks it. It must be completed with the `ci-ok` job
#    green; anything else ends the check (exit 2), since there is no green run to judge. A list
#    of runs or jobs that fills its page of 100 ends it too.
# 4. The main it tested: the run object does not say, but actions/checkout logs
#    `HEAD is now at <sha> Merge <head> into <main>` in each job that checks out. Every job log of
#    the run's attempt is read and all such lines must agree; <head> must be the pull request's
#    head, and <main> must be on origin/main. Logs expire with GitHub's retention; then the check
#    says so.
# 5. The pull request's files (`git diff --no-renames -z <merge base> <head>`, so a rename counts
#    under both names and no name is quoted), and the main commits outside the tested merge
#    (`git rev-list <main> ^<tested main> ^<head>`). Such a commit, a merge included, is a gap
#    when it changes one of the files against any of its parents.
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

# A job log is plain text with the runner's colour codes. gh 2.97.0 and later refuse to print a
# non-JSON body with terminal escape sequences unless told --allow-escape-sequences, which older gh
# rejects as an unknown flag; so the flag is passed when `gh api --help` lists it.
gh_help=$(gh api --help 2>&1) || die "gh api --help failed: ${gh_help//$'\n'/ }"
log_flags=()
grep -q -e '--allow-escape-sequences' <<<"$gh_help" && log_flags=(--allow-escape-sequences)

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

# 2. Main and the head, each fetched under a ref of this run only: origin/main may not be what this
# fetch brought (a clone whose fetch refspec leaves it alone keeps an old one). A shallow clone may
# lack the history the merge base and the commits are read from, so it is refused.
shallow=$(git rev-parse --is-shallow-repository) || die "git rev-parse --is-shallow-repository failed"
[ "$shallow" = false ] || die "this is a shallow clone; run it in a full clone (git fetch --unshallow)"
tmp="refs/maity-coverage/$$"
listing=""
errors=""
cleanup() {
  git update-ref -d "$tmp/main" 2>/dev/null
  git update-ref -d "$tmp/head" 2>/dev/null
  [ -z "$listing" ] || rm -f "$listing"
  [ -z "$errors" ] || rm -f "$errors"
}
trap cleanup EXIT
git fetch --quiet --no-tags origin "+refs/heads/main:$tmp/main" "+refs/pull/$pr/head:$tmp/head" \
  || die "git fetch of origin's main and #$pr's head failed"
main=$(git rev-parse --verify --quiet "$tmp/main^{commit}") || die "no fetched main"
fetched=$(git rev-parse --verify --quiet "$tmp/head^{commit}") || die "no fetched head of #$pr"
[ "$fetched" = "$head" ] || die "#$pr is at $head on GitHub but at $fetched on origin; run again"

# 3. The newest ci run for exactly this head and branch.
runs=$(api "$repo/actions/runs?head_sha=$head&event=pull_request&per_page=100" \
  --jq '.workflow_runs[] | "\(.created_at) \(.id) \(.run_attempt) \(.status) \(.conclusion) \(.path) \(.head_branch)"') \
  || die "listing the ci runs of $head failed (gh api)"
# One page of 100 is read; a full page may have more after it, so the check does not guess.
[ "$(grep -c . <<<"$runs")" -lt 100 ] || die "$head has 100 or more ci runs; only one page is read"
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
[ "$(grep -c . <<<"$jobs")" -lt 100 ] || die "run $run_id has 100 or more jobs; only one page is read"
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

# 4. The main the run tested, from actions/checkout's log line. Every job that ran is read, and all
# that name a merge must name the same one.
merge=""
merge_job=""
errors=$(mktemp) || die "mktemp failed"
for job in ${job_ids[@]+"${job_ids[@]}"}; do
  log=$(api ${log_flags[@]+"${log_flags[@]}"} "$repo/actions/jobs/$job/logs" 2>"$errors") \
    || die "reading the log of job $job failed: $(tr '\n' ' ' <"$errors")(GitHub expires logs after its retention)"
  merges=$(grep -oE 'HEAD is now at [0-9a-f]+ Merge [0-9a-f]{40} into [0-9a-f]{40}' <<<"$log" | cut -d' ' -f6- | LC_ALL=C sort -u)
  [ -n "$merges" ] || continue
  [ "$(wc -l <<<"$merges")" -eq 1 ] || die "job $job's log names more than one merge: ${merges//$'\n'/; }"
  if [ -z "$merge" ]; then
    merge=$merges
    merge_job=$job
  elif [ "$merges" != "$merge" ]; then
    die "jobs $merge_job and $job of run $run_id name different merges ($merge; $merges): $run_url"
  fi
done
[ -n "$merge" ] || die "no job log of run $run_id names the merge it tested: $run_url"
merged_head=$(cut -d' ' -f2 <<<"$merge")
tested=$(cut -d' ' -f4 <<<"$merge")
[ "$merged_head" = "$head" ] \
  || die "run $run_id tested a merge of $merged_head, not of #$pr's head $head: $run_url"
git cat-file -e "$tested^{commit}" 2>/dev/null || die "the tested main $tested is not in this clone"
git merge-base --is-ancestor "$tested" "$main"
case $? in
  0) ;;
  1) die "the tested main $tested is not on origin/main" ;;
  *) die "git merge-base --is-ancestor $tested $main failed" ;;
esac

# 5. The pull request's files, NUL-separated so that no name is quoted (git quotes a newline, a tab,
# a double quote and a backslash even with core.quotePath=false), and the main commits the tested
# merge lacks: on main, in neither the tested main nor the head (a main the pull request merged is
# in the tested merge through the head). A commit counts when it changes one of the files against
# any of its parents, so a merge counts both for an edit of its own and for a side it takes.
base=$(git merge-base "$main" "$head") || die "no merge base of origin/main and $head"
listing=$(mktemp) || die "mktemp failed"
git diff --no-renames --name-only -z "$base" "$head" >"$listing" || die "git diff $base $head failed"
mapfile -d '' -t paths <"$listing" || die "reading the file list of #$pr failed"
echo "coverage: #$pr at $head; $SUMMARY_JOB green in $run_url"
echo "coverage: that run tested the merge with main $tested; merge base $base"
if [ "${#paths[@]}" -eq 0 ]; then
  echo "coverage: #$pr changes no file against its merge base"
  exit 0
fi
commits=$(git rev-list "$main" "^$tested" "^$head") || die "git rev-list of main's commits after $tested failed"
missing=0
while IFS= read -r commit; do
  [ -n "$commit" ] || continue
  parents=$(git rev-parse "$commit^@") || die "git rev-parse $commit^@ failed"
  touched=""
  while IFS= read -r parent; do
    [ -n "$parent" ] || die "$commit has no parent"
    git diff --quiet --no-renames "$parent" "$commit" -- "${paths[@]}"
    case $? in
      0) continue ;;
      1) ;;
      *) die "git diff $parent $commit failed" ;;
    esac
    names=$(git diff --no-renames --name-only "$parent" "$commit" -- "${paths[@]}") \
      || die "git diff $parent $commit failed"
    touched+="$names"$'\n'
  done <<<"$parents"
  [ -n "$touched" ] || continue
  missing=$((missing + 1))
  subject=$(git log -1 --format=%s "$commit") || die "git log $commit failed"
  # A subject is text from the commit; no control character of it reaches the terminal.
  subject=$(printf '%s' "$subject" | LC_ALL=C tr '\000-\037\177' '?') || die "tr failed"
  touched=$(LC_ALL=C sort -u <<<"$touched" | sed '/^$/d' | paste -sd, -) || die "listing the files of $commit failed"
  echo "  $commit $subject [$touched]"
done <<<"$commits"

# For information only: merge-tree of today's main with the head prints a tree id and nothing
# about which main commits a run has seen.
tree=$(git merge-tree --write-tree --no-messages "$main" "$head" 2>/dev/null | head -1)
echo "coverage: merge-tree of origin/main with the head today: exit ${PIPESTATUS[0]}, tree ${tree:-none}"

if [ "$missing" -gt 0 ]; then
  echo "coverage: $missing main commits on #$pr's files are not in the tested main;" \
    "merge origin/main into the branch and push for a new $SUMMARY_JOB run (a re-run tests the old merge again)"
  exit 1
fi
echo "coverage: every main commit on #$pr's files is in the tested main"
exit 0
