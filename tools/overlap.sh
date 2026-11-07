#!/usr/bin/env bash
# The overlap check before a push: which open pull requests change the same files as a branch,
# and whether the branch merges with each of them.
#
#   tools/overlap.sh [<branch>]       # default: the checked-out branch
#
# It fetches the head of every open pull request of origin's repository (listed over GitHub's
# REST API, `gh api .../pulls`), checks that it is the head gh listed, and keeps those that change a file the branch changes, each
# against origin/main (`git diff --no-renames base...head`, so a renamed file counts under its
# old name as well). For each one it runs
# `git merge-tree --write-tree` of the branch with the pull request's head and decides by the
# exit code alone (0 clean, 1 conflict), never by git's message, which is in the locale's
# language (KONFLIKT, CONFLICT, ...). For each conflict it runs the same check of origin/main
# with that pull request, so the line says whether the conflict already exists without the
# branch.
#
# One line per pull request: its number, the shared files, and `clean` or the conflicting
# files. A file that conflicts with origin/main alone is the other pull request's to resolve
# and is named, not counted. Exit 0 means the branch adds no conflict, which is weaker than
# "merges cleanly": a file that conflicts against both counts as already conflicting, even if
# the branch changes how; read that pull request's line. Exit 1 when the branch adds a
# conflict, 2 when the check could not run: every command whose answer it needs stops the
# check when it fails, so a check that did not run never ends in 0.
# MAITY_OVERLAP_NO_FETCH=1 skips `git fetch origin main` (the tests set it).
set -uo pipefail

die() {
  echo "overlap: $*" >&2
  exit 2
}

# Paths as git stores them, not quoted octal: one form for every list, and readable.
git() {
  command git -c core.quotePath=false "$@"
}

# Path lists, one path a line, sorted bytewise: `sort` follows the locale's collation
# otherwise. git itself keeps the reader's locale; only its exit codes are read.
paths() {
  LC_ALL=C sort -u
}

# The lines of list $1 that are (keep=1) or are not (keep=0) in list $2, in $1's order, one a
# line. Bash alone, no other program: no exit status of a helper can get lost on the way, as
# one inside `<(...)` would, outside pipefail.
pick() {
  local -A seen=()
  local line
  while IFS= read -r line; do
    [ -n "$line" ] && seen["p/$line"]=1
  done <<<"$2"
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    if [ -n "${seen["p/$line"]+x}" ]; then
      [ "$3" = 1 ] && printf '%s\n' "$line"
    else
      [ "$3" = 0 ] && printf '%s\n' "$line"
    fi
  done <<<"$1"
  return 0
}

# A list as the output names it: comma-separated.
named() {
  local list=${1%$'\n'}
  printf '%s' "${list//$'\n'/,}"
}

# The files $2 changes against its merge base with $1, sorted. No merge base (unrelated
# history) or any other failure stops the check: an empty list would read as "no file".
changed() {
  local out
  out=$(git diff --no-renames --name-only "$1...$2") || die "git diff $1...$2 failed"
  printf '%s\n' "$out" | sed '/^$/d' | paths || die "sorting the files of $2 failed"
}

# `pick` keeps a set in an associative array; bash 3 (macOS's own) has none.
[ "${BASH_VERSINFO[0]}" -ge 4 ] || die "needs bash 4 or newer"
command -v gh >/dev/null || die "needs the gh CLI"
branch="${1:-$(git branch --show-current)}"
[ -n "$branch" ] || die "no branch given and none checked out"
own=$(git rev-parse --verify --quiet "$branch^{commit}") || die "no branch $branch"

if [ "${MAITY_OVERLAP_NO_FETCH:-}" != 1 ]; then
  git fetch --quiet origin main || die "git fetch origin main failed"
fi
base=$(git rev-parse --verify --quiet origin/main) || die "no origin/main"

# A three-way merge of $1 and $2 by git's exit code: sets `merge_status` (0 clean, 1 conflict)
# and `merge_files` (the conflicting paths, one a line). Any other exit (a missing
# object, unrelated history, an old git without --write-tree) stops the check: it is never
# read as "clean". A conflict without a file stops it too, since nothing could be compared.
merge_check() {
  local out
  out=$(git merge-tree --write-tree --name-only --no-messages "$1" "$2" 2>/dev/null)
  merge_status=$?
  merge_files=""
  case $merge_status in
    0) ;;
    1)
      merge_files=$(printf '%s\n' "$out" | sed -n '2,$p' | sed '/^$/d' | paths) \
        || die "reading the conflicts of $1 and $2 failed"
      [ -n "$merge_files" ] || die "git merge-tree $1 $2 named a conflict but no file"
      ;;
    *) die "git merge-tree $1 $2 failed with exit $merge_status" ;;
  esac
}

mine=$(changed "$base" "$branch") || exit 2
if [ -z "$mine" ]; then
  echo "overlap: $branch changes no file against origin/main"
  exit 0
fi

# The open pull requests of origin's repository, over REST: `gh pr list` asks GitHub's GraphQL
# API, which some sessions cannot reach (HTTP 403 in Claude Code's cloud sessions). The owner and
# name are the last two parts of origin's URL (https://github.com/o/r.git, git@github.com:o/r.git,
# or a proxy's http://host/git/o/r), never gh's own choice: on its own it may name another
# repository (GH_REPO, `gh repo set-default`, an `upstream` remote), whose pull requests are other
# changes or none. The host is origin's too, given to gh with --hostname: gh's own (GH_HOST, or
# the one host it is logged in to) could be another server, whose empty list of a repository of
# the same name would read as "no open pull request" with nothing left to compare.
# The URL as configured: `git remote get-url` applies url.<base>.insteadOf, which can name a
# mirror whose path is not the repository's on GitHub.
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
# The host: scheme://[user@]host[:port]/... or scp's [user@]host:path. A host on the loopback is
# a proxy in front of github.com (Claude Code's cloud sessions fetch through one), which serves
# git and not the API. A URL without a host (a local path) names no server to ask.
case $origin in
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
# Loopback by its literal form only: a name such as 127.example.com is a server of its own.
if [[ $repo_host == localhost || $repo_host == "[::1]" || $repo_host =~ ^127(\.[0-9]{1,3}){3}$ ]]; then
  repo_host=github.com
fi
[[ $repo_host =~ ^[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]$ ]] \
  || die "cannot read a host from origin's URL $origin"
# Every page: --paginate follows GitHub's links to the last one, and a page that fails ends gh
# with an error. A deleted fork has no head repository (null), which counts as a fork.
# Sets `prs` (one line a pull request) and `pr_count`.
PAGE=100
list_prs() {
  local line
  prs=$(gh api --hostname "$repo_host" --paginate "repos/$repo_owner/$repo_name/pulls?state=open&per_page=$PAGE" \
    --jq '.[] | "\(.number) \(.head.sha) \(.head.repo.full_name != .base.repo.full_name) \(.head.ref)"') \
    || die "listing the open pull requests of $repo_owner/$repo_name on $repo_host failed (gh api)"
  # Every line as the list writes it, checked in bash: an answer of another shape (an error
  # object instead of a list, a field GitHub renamed) would otherwise read as fewer pull requests.
  pr_count=0
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    [[ $line =~ ^[0-9]+\ ([0-9a-f]{40}|[0-9a-f]{64})\ (true|false)\ [^\ ]+$ ]] \
      || die "unexpected line in the list of open pull requests: $line"
    pr_count=$((pr_count + 1))
  done <<<"$prs"
}
list_prs
# GitHub pages this list by offset: a pull request that closes on a page already read moves the
# first one of the next page onto it, and no page returns that one. A list of a full page or more
# may have taken more than one request (a skip can leave exactly $PAGE lines) and is read again;
# it must name the same pull requests at the same heads. Fewer lines than a page were one request,
# which cannot shift. A skip leaves the closed pull request in the first read and out of the
# second, so the two differ unless the same churn repeats during the second read; any other
# change between them stops the check too, and running again settles it.
if [ "$pr_count" -ge "$PAGE" ]; then
  first=$prs
  list_prs
  gone=$(pick "$first" "$prs" 0) || die "comparing the two lists of open pull requests failed"
  new=$(pick "$prs" "$first" 0) || die "comparing the two lists of open pull requests failed"
  [ -z "$gone$new" ] || die "the list of open pull requests changed while it was read; run again"
fi

# Every other pull request's head in one fetch, under refs of this run only.
tmp="refs/maity-overlap/$$"
trap 'git for-each-ref --format="%(refname)" "$tmp" | xargs -r -n1 git update-ref -d' EXIT
numbers=()
specs=()
declare -A listed=()
while read -r number head fork name; do
  [ -n "${number:-}" ] || continue
  # The branch's own pull request, also while its pushed head is older than the branch: by its
  # head, or by its branch name in this repository. A fork's branch of the same name is another's.
  [ "$head" = "$own" ] && continue
  [ "$fork" = false ] && [ "$name" = "$branch" ] && continue
  numbers+=("$number")
  listed[$number]=$head
  specs+=("+refs/pull/$number/head:$tmp/$number")
done <<<"$prs"
if [ "${#specs[@]}" -gt 0 ]; then
  git fetch --quiet --no-tags origin "${specs[@]}" || die "fetching the heads of pull requests ${numbers[*]} failed"
fi
# The head checked must be the head gh listed, or the check reads another change than the one
# listed: a push between the list and the fetch moves it (running again settles that), and this
# still holds should gh and origin ever name different repositories (another host, a renamed
# repository).
for number in ${numbers[@]+"${numbers[@]}"}; do
  fetched=$(git rev-parse --verify --quiet "$tmp/$number^{commit}") || die "no fetched head of pull request $number"
  [ "$fetched" = "${listed[$number]}" ] \
    || die "pull request $number is at ${listed[$number]} in gh's list but at $fetched on origin"
done

found=0
conflicts=0
for number in ${numbers[@]+"${numbers[@]}"}; do
  ref="$tmp/$number"
  theirs=$(changed "$base" "$ref") || exit 2
  shared=$(pick "$mine" "$theirs" 1) || die "comparing the files of pull request $number failed"
  [ -n "$shared" ] || continue
  found=$((found + 1))
  shared=$(named "$shared") || die "naming the files of pull request $number failed"
  merge_check "$branch" "$ref"
  if [ "$merge_status" -eq 0 ]; then
    echo "#$number [$shared]: clean"
  else
    files=$merge_files
    merge_check "$base" "$ref"
    already=$merge_files
    # The conflicts the branch adds: files that conflict with it and not with origin/main alone.
    added=$(pick "$files" "$already" 0) || die "comparing the conflicts of pull request $number failed"
    if [ -n "$added" ]; then
      conflicts=$((conflicts + 1))
      echo "#$number [$shared]: CONFLICT in $(named "$added")${already:+ (and against origin/main alone in $(named "$already"))}"
    else
      echo "#$number [$shared]: clean for this branch; conflicts with origin/main alone in $(named "$already")"
    fi
  fi
done

[ "$found" -gt 0 ] || echo "overlap: no open pull request changes a file of $branch"
[ "$conflicts" -eq 0 ]
