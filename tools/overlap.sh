#!/usr/bin/env bash
# The overlap check before a push: which open pull requests change the same files as a branch,
# and whether the branch merges with each of them.
#
#   tools/overlap.sh [<branch>]       # default: the checked-out branch
#
# It fetches the head of every open pull request (`gh pr list`) and keeps those that change a
# file the branch changes, each against origin/main (`git diff --no-renames base...head`, so a
# renamed file counts under its old name as well). For each one it runs
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

# The most open pull requests read at once; a list that reaches it may be cut short.
LIMIT=1000

die() {
  echo "overlap: $*" >&2
  exit 2
}

# Paths as git stores them, not quoted octal: one form for every list, and readable.
git() {
  command git -c core.quotePath=false "$@"
}

# Path lists sorted and compared bytewise: `sort` and `comm` follow the locale's collation
# otherwise, which can order or equate paths differently between the two (a German locale
# warned "not in sorted order"). git itself keeps the reader's locale; only its exit codes
# are read.
paths() {
  LC_ALL=C sort -u
}

# The files $2 changes against its merge base with $1, sorted. No merge base (unrelated
# history) or any other failure stops the check: an empty list would read as "no file".
changed() {
  local out
  out=$(git diff --no-renames --name-only "$1...$2") || die "git diff $1...$2 failed"
  printf '%s\n' "$out" | sed '/^$/d' | paths || die "sorting the files of $2 failed"
}

command -v gh >/dev/null || die "needs the gh CLI"
branch="${1:-$(git branch --show-current)}"
[ -n "$branch" ] || die "no branch given and none checked out"
own=$(git rev-parse --verify --quiet "$branch^{commit}") || die "no branch $branch"

if [ "${MAITY_OVERLAP_NO_FETCH:-}" != 1 ]; then
  git fetch --quiet origin main || die "git fetch origin main failed"
fi
base=$(git rev-parse --verify --quiet origin/main) || die "no origin/main"

# A three-way merge of $1 and $2 by git's exit code: sets `merge_status` (0 clean, 1 conflict)
# and `merge_files` (the conflicting paths, comma-separated). Any other exit (a missing
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
      merge_files=$(printf '%s\n' "$out" | sed -n '2,$p' | sed '/^$/d' | paths | paste -sd, -) \
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

prs=$(gh pr list --state open --limit "$LIMIT" --json number,headRefOid,headRefName \
  --jq '.[] | "\(.number) \(.headRefOid) \(.headRefName)"') || die "gh pr list failed"
count=$(printf '%s' "$prs" | grep -c '^') || true
[ "$count" -lt "$LIMIT" ] || die "$count open pull requests, the list may be cut short at $LIMIT"

# Every other pull request's head in one fetch, under refs of this run only.
tmp="refs/maity-overlap/$$"
trap 'git for-each-ref --format="%(refname)" "$tmp" | xargs -r -n1 git update-ref -d' EXIT
numbers=()
specs=()
while read -r number head name; do
  [ -n "${number:-}" ] || continue
  # The branch's own pull request, also while its pushed head is older than the branch.
  [ "$head" = "$own" ] || [ "$name" = "$branch" ] && continue
  numbers+=("$number")
  specs+=("+refs/pull/$number/head:$tmp/$number")
done <<<"$prs"
if [ "${#specs[@]}" -gt 0 ]; then
  git fetch --quiet --no-tags origin "${specs[@]}" || die "fetching the heads of pull requests ${numbers[*]} failed"
fi

found=0
conflicts=0
for number in "${numbers[@]}"; do
  ref="$tmp/$number"
  theirs=$(changed "$base" "$ref") || exit 2
  shared=$(LC_ALL=C comm -12 <(printf '%s\n' "$mine") <(printf '%s\n' "$theirs") | sed '/^$/d' | paste -sd, -) \
    || die "comparing the files of pull request $number failed"
  [ -n "$shared" ] || continue
  found=$((found + 1))
  merge_check "$branch" "$ref"
  if [ "$merge_status" -eq 0 ]; then
    echo "#$number [$shared]: clean"
  else
    files=$merge_files
    merge_check "$base" "$ref"
    already=$merge_files
    # The conflicts the branch adds: files that conflict with it and not with origin/main alone.
    added=$(LC_ALL=C comm -23 <(tr , '\n' <<<"$files") <(tr , '\n' <<<"$already") | sed '/^$/d' | paste -sd, -) \
      || die "comparing the conflicts of pull request $number failed"
    if [ -n "$added" ]; then
      conflicts=$((conflicts + 1))
      echo "#$number [$shared]: CONFLICT in $added${already:+ (and against origin/main alone in $already)}"
    else
      echo "#$number [$shared]: clean for this branch; conflicts with origin/main alone in $already"
    fi
  fi
done

[ "$found" -gt 0 ] || echo "overlap: no open pull request changes a file of $branch"
[ "$conflicts" -eq 0 ]
