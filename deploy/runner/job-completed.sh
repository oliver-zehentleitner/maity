#!/bin/bash
# ACTIONS_RUNNER_HOOK_JOB_COMPLETED: tidy up after a job. This is housekeeping, not a
# boundary: a job runs as the runner user and can leave things this script does not reach
# (see README.md). Install it OUTSIDE the runner's directory (/opt/maity-runner-hooks/).
# Its output lands in the job's log, the step "Complete runner", which is public in a
# public repository: it prints only what is safe to publish.
# Runs as the runner's own user; its Docker is the rootless one of that user.
: "${RUNNER_WORKSPACE:?RUNNER_WORKSPACE not set, nothing cleaned}"
: "${RUNNER_TEMP:?RUNNER_TEMP not set, nothing cleaned}"
status=0
step() { "$@" >/dev/null || { echo "job-completed: '$*' failed" >&2; status=1; }; }
containers=$(docker ps -aq) || { echo "job-completed: docker ps failed" >&2; status=1; }
[ -z "${containers:-}" ] || step docker rm -f $containers
step docker network prune -f
step docker volume prune -af
step docker image prune -af
step docker builder prune -af
# The checkout and the temp files of the job; the tool cache (Python) stays.
find "$RUNNER_WORKSPACE" "$RUNNER_TEMP" -mindepth 1 -maxdepth 1 -exec rm -rf {} + \
  || { echo "job-completed: cleaning the workspace failed" >&2; status=1; }
exit $status
