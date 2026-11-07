#!/usr/bin/env bash
# The guard tests before a review request, in one run of seconds instead of a CI round each:
#
#   tools/guards.sh                   # HUB_PYTHON: a Python with hub/'s test requirements
#
# 1. hub/tests/test_per_human_tables.py: a new column that names a human is decided for the
#    account deletion and the export (docs/api.md §2.9).
# 2. make -C web shapes: tools/hub-shapes.json is rewritten from the hub as it is now.
# 3. make -C web fixtures: the generated files (fixtures/fixtures.js, js/i18n/*.js) are
#    rewritten from their sources.
# 4. make -C web check: among others, the fixture hub answers in the hub's shapes. A field the
#    hub sends and a fixture lacks is named; add it to the fixture under web/fixtures/ by hand.
#    tools/fixture-shapes-baseline.json is never extended for it.
# 5. git status is clean: whatever steps 2 and 3 rewrote belongs in a commit.
#
# Every step runs, so one run names every failure. Exit 0 when all pass, 1 when a guard fails
# (the steps that failed are named), 2 when the guards could not run: no git work tree, a work
# tree not clean before the run (step 5 could not tell the run's changes from the author's),
# a HUB_PYTHON without pytest or one that would test another checkout's hub. A run that did
# not check never ends in 0.
set -uo pipefail
# Messages from git, make and Python in one language, whatever the reader's locale.
export LC_ALL=C

die() {
  echo "guards: $*" >&2
  exit 2
}

root=$(git rev-parse --show-toplevel 2>/dev/null) || die "not in a git work tree"
cd "$root" || die "cannot enter $root"
hub_python=${HUB_PYTHON:-python3}

dirty=$(git status --porcelain) || die "git status failed"
[ -z "$dirty" ] || die "the work tree is not clean; commit or set aside first:
$dirty"

command -v make >/dev/null || die "needs make"
command -v node >/dev/null || die "needs node (web/tools/check.py runs the fixture hub)"
# The hub of this work tree, never one installed from another checkout (`pip install -e`
# elsewhere would test that one's tables and shapes, and pass for the wrong code).
export PYTHONPATH="$root/hub/src${PYTHONPATH:+:$PYTHONPATH}"
hub_src=$("$hub_python" -c 'import pytest, maity_hub; print(maity_hub.__file__)') \
  || die "HUB_PYTHON=$hub_python lacks pytest or the hub's requirements"
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
  bash -c 'cd hub && "$0" -m pytest -q -p no:cacheprovider tests/test_per_human_tables.py' "$hub_python"
step "web shapes" make -C web shapes HUB_PYTHON="$hub_python"
step "web fixtures" make -C web fixtures
step "web check" make -C web check

changed=$(git status --porcelain) || die "git status failed"
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
