#!/usr/bin/env bash
# The guard tests before a review request, in one run of seconds instead of a CI round each:
#
#   tools/guards.sh                   # HUB_PYTHON: a Python with hub/'s test requirements
#
# 1. hub/tests/test_per_human_tables.py: a new column that names a human is decided for the
#    account deletion and the export (docs/api.md §2.9).
# 2. make -C web shapes: web/tools/hub-shapes.json is rewritten from the hub as it is now.
# 3. make -C web fixtures: the generated files (fixtures/fixtures.js, js/i18n/*.js) are
#    rewritten from their sources.
# 4. make -C web check: among others, the fixture hub answers in the hub's shapes. A field the
#    hub sends and a fixture lacks is named; add it to the fixture under web/fixtures/ by hand.
#    web/tools/fixture-shapes-baseline.json is never extended for it.
# 5. git status is clean: whatever steps 2 and 3 rewrote belongs in a commit.
#
# Every step runs, so one run names every failure. Exit 0 when all pass, 1 when a guard fails
# (the steps that failed are named), 2 when the guards could not run: no git work tree, a work
# tree not clean before the run (step 5 could not tell the run's changes from the author's),
# no make, node or HUB_PYTHON, a HUB_PYTHON without pytest or one that would test another
# checkout's hub. A run that did not check never ends in 0: every step runs in an environment
# of its own (see `clean`), so no inherited setting can make it pass without testing.
set -uo pipefail
# Messages from git, make and Python in one language, whatever the reader's locale.
export LC_ALL=C

die() {
  echo "guards: $*" >&2
  exit 2
}

# HUB_PYTHON as an absolute path, resolved where the caller stands: the steps run it from
# hub/ and web/, where a relative path or a bare name could name another file or none.
# A bare name is looked up on PATH first, and what that gives can still be relative (a PATH
# entry such as `.venv/bin`).
hub_python=${HUB_PYTHON:-python3}
case $hub_python in
  */*) ;;
  *) hub_python=$(command -v "$hub_python") || die "no ${HUB_PYTHON:-python3} on PATH (HUB_PYTHON)" ;;
esac
case $hub_python in
  /*) ;;
  *) hub_python="$PWD/$hub_python" ;;
esac
# git takes its repository, index and settings from GIT_* variables as well; this work tree's
# own, as found from where the caller stands, is the one checked.
for v in $(compgen -e); do
  case $v in GIT_*) unset "$v" ;; esac
done
root=$(git rev-parse --show-toplevel 2>/dev/null) || die "not in a git work tree"
cd "$root" || die "cannot enter $root"

# The work tree's changes, as step 5 reads them: tracked files from git status, untracked ones
# by the repository's .gitignore files alone. A personal exclude (core.excludesFile,
# .git/info/exclude) or status.showUntrackedFiles=no could otherwise hide a file a step wrote.
tree_changes() {
  git status --porcelain --untracked-files=no || return 1
  git ls-files --others --exclude-per-directory=.gitignore | sed 's/^/?? /'
}
dirty=$(tree_changes) || die "git status failed"
[ -z "$dirty" ] || die "the work tree is not clean; commit or set aside first:
$dirty"
# git status leaves out a file whose index entry says skip-worktree (S, also set by a sparse
# checkout) or assume-unchanged (a lowercase tag): a step could rewrite it unseen.
entries=$(git ls-files -v) || die "git ls-files failed"
flagged=""
while IFS= read -r entry; do
  case $entry in
    "S "* | [a-z]" "*) flagged+="${entry#? }"$'\n' ;;
  esac
done <<<"$entries"
[ -z "$flagged" ] || die "git status would not show these files (skip-worktree or assume-unchanged); clear the flag first:
$flagged"

command -v make >/dev/null || die "needs make"
command -v node >/dev/null || die "needs node (web/tools/check.py runs the fixture hub)"
# Each step, and the check of the hub below, runs with only these variables. Inherited, any of
# PYTEST_ADDOPTS (--collect-only, -k), PYTEST_PLUGINS, MAKEFLAGS (-n, -i, -k, -t), MAKEFILES, a
# PYTHON or NODE that takes over make's own, BASH_ENV, NODE_OPTIONS or PYTHONSTARTUP could let a
# step end in 0 without testing; a list of what to drop would miss the next one. PYTHONPATH is
# this work tree's hub alone, never one installed from another checkout (`pip install -e`
# elsewhere would test that one's tables and shapes, and pass for the wrong code).
keep=(PATH="$PATH" HOME="${HOME:-/}" LC_ALL=C PYTHONPATH="$root/hub/src" PYTHONNOUSERSITE=1)
[ -n "${TMPDIR:-}" ] && keep+=(TMPDIR="$TMPDIR")
clean() {
  env -i "${keep[@]}" "$@"
}
[ -x "$hub_python" ] || die "HUB_PYTHON=$hub_python is not an executable file"
hub_src=$(clean "$hub_python" -c 'import pytest, maity_hub; print(maity_hub.__file__)') \
  || die "HUB_PYTHON=$hub_python cannot import pytest and the hub in the steps' cleared environment: it lacks them, or needs a variable that environment drops (LD_LIBRARY_PATH, for one)"
case $hub_src in
  "$root/hub/src/"*) ;;
  *) die "HUB_PYTHON=$hub_python imports the hub from $hub_src, not from $root/hub/src" ;;
esac

failed=()
step() {
  local name=$1
  shift
  echo "guards: $name"
  if ! "$@"; then
    failed+=("$name")
  fi
}

step "per-human tables" \
  clean bash -c 'cd hub && "$0" -m pytest -q -p no:cacheprovider tests/test_per_human_tables.py' "$hub_python"
step "web shapes" clean make -C web shapes HUB_PYTHON="$hub_python"
step "web fixtures" clean make -C web fixtures
step "web check" clean make -C web check

changed=$(tree_changes) || die "git status failed"
if [ -n "$changed" ]; then
  echo "guards: these files changed; commit them:" >&2
  printf '%s\n' "$changed" >&2
  failed+=("clean work tree")
fi

if [ "${#failed[@]}" -gt 0 ]; then
  printf 'guards: FAILED: %s\n' "${failed[@]}" >&2
  exit 1
fi
echo "guards: all passed"
