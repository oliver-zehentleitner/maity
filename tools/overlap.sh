#!/usr/bin/env bash
# The overlap check before a push: which open pull requests change the same files as a branch,
# and whether the branch merges with each of them.
#
#   tools/overlap.sh [<branch>]       # default: the checked-out branch
#
# It lists the open pull requests (`gh pr list`) that change a file the branch changes against
# origin/main. For each one it runs `git merge-tree --write-tree` of the branch with the pull
# request's head and decides by the exit code alone (0 clean, 1 conflict), never by git's
# message, which is in the locale's language (KONFLIKT, CONFLICT, ...). For each conflict it
# runs the same check of origin/main with that pull request, so the line says whether the
# conflict already exists without the branch.
#
# One line per pull request: its number, the shared files, and `clean` or the conflicting
# files. A file that conflicts the same way with origin/main alone is the other pull request's
# to resolve and is named, not counted. Exit 0 when the branch adds no conflict, 1 when it adds
# one, 2 when the check could not run. A file that conflicts against both counts as already
# conflicting, even if the branch changes how: read that pull request's line. MAITY_OVERLAP_NO_FETCH=1 skips `git fetch origin main` (the tests set it).
set -uo pipefail

die() {
  echo "overlap: $*" >&2
  exit 2
}

# Path lists sorted and compared bytewise: `sort` and `comm` follow the locale's collation
# otherwise, which can order or equate paths differently between the two (a German locale
# warned "not in sorted order"). git itself keeps the reader's locale; only its exit codes
# are read.
paths() {
  LC_ALL=C sort -u
}

command -v gh >/dev/null || die "needs the gh CLI"
git merge-tree --help >/dev/null 2>&1 || die "needs git"
branch="${1:-$(git branch --show-current)}"
[ -n "$branch" ] || die "no branch given and none checked out"
git rev-parse --verify --quiet "$branch^{commit}" >/dev/null || die "no branch $branch"

if [ "${MAITY_OVERLAP_NO_FETCH:-}" != 1 ]; then
  git fetch --quiet origin main || die "git fetch origin main failed"
fi
base=$(git rev-parse --verify --quiet origin/main) || die "no origin/main"

# A three-way merge of $1 and $2 by git's exit code: sets `merge_status` (0 clean, 1 conflict)
# and `merge_files` (the conflicting paths, comma-separated). Any other exit (a missing
# object, an old git) stops the check: it is never read as "clean".
merge_check() {
  local out
  out=$(git merge-tree --write-tree --name-only --no-messages "$1" "$2" 2>/dev/null)
  merge_status=$?
  merge_files=""
  case $merge_status in
    0) ;;
    1) merge_files=$(printf '%s\n' "$out" | sed -n '2,$p' | sed '/^$/d' | paths | paste -sd, -) ;;
    *) die "git merge-tree $1 $2 failed with exit $merge_status" ;;
  esac
}

mine=$(git diff --name-only "$base...$branch" | paths)
if [ -z "$mine" ]; then
  echo "overlap: $branch changes no file against origin/main"
  exit 0
fi

own=$(git rev-parse "$branch")
prs=$(gh pr list --state open --limit 200 --json number,headRefOid --jq '.[] | "\(.number) \(.headRefOid)"') \
  || die "gh pr list failed"

found=0
conflicts=0
tmp="refs/maity-overlap/$$"
trap 'git for-each-ref --format="%(refname)" "$tmp" | xargs -r -n1 git update-ref -d' EXIT
while read -r number head; do
  [ -n "${number:-}" ] || continue
  [ "$head" = "$own" ] && continue  # the branch's own pull request
  theirs=$(gh pr view "$number" --json files --jq '.files[].path' | paths) \
    || die "gh pr view $number failed"
  shared=$(LC_ALL=C comm -12 <(printf '%s\n' "$mine") <(printf '%s\n' "$theirs") | paste -sd, -)
  [ -n "$shared" ] || continue
  found=$((found + 1))
  ref="$tmp/$number"
  git fetch --quiet origin "+refs/pull/$number/head:$ref" || die "fetching pull request $number failed"
  merge_check "$branch" "$ref"
  if [ "$merge_status" -eq 0 ]; then
    echo "#$number [$shared]: clean"
  else
    files=$merge_files
    merge_check "$base" "$ref"
    already=$merge_files
    # The conflicts the branch adds: files that conflict with it and not with origin/main alone.
    added=$(LC_ALL=C comm -23 <(tr , '\n' <<<"$files") <(tr , '\n' <<<"$already") | paste -sd, -)
    if [ -n "$added" ]; then
      conflicts=$((conflicts + 1))
      echo "#$number [$shared]: CONFLICT in $added${already:+ (and against origin/main alone in $already)}"
    else
      echo "#$number [$shared]: clean for this branch; conflicts with origin/main alone in $already"
    fi
  fi
done <<<"$prs"

[ "$found" -gt 0 ] || echo "overlap: no open pull request changes a file of $branch"
[ "$conflicts" -eq 0 ]
