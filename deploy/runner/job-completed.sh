#!/bin/bash
# ACTIONS_RUNNER_HOOK_JOB_COMPLETED: tidy up after a job. This is housekeeping, not a
# boundary: a job runs as the runner user and can leave things this script does not reach
# (see README.md). Install it OUTSIDE the runner's directory (/opt/maity-runner-hooks/).
# Its output lands in the job's log, the step "Complete runner", which is public in a
# public repository: it prints only what is safe to publish.
# Runs as the runner's own user; its Docker is the rootless one of that user, SHARED by every
# runner instance of the machine (maity-runner@sqlite, @pg, @maria run side by side). So nothing here
# may touch a container, network or image another instance's job is using right now: the Actions
# runner stops the service containers of its own job itself ("Stop containers"); this hook only
# removes what is stopped, unused or old.
: "${RUNNER_WORKSPACE:?RUNNER_WORKSPACE not set, nothing cleaned}"
: "${RUNNER_TEMP:?RUNNER_TEMP not set, nothing cleaned}"
status=0
step() { "$@" >/dev/null || { echo "job-completed: '$*' failed" >&2; status=1; }; }
step docker container prune -f --filter until=1h   # stopped containers left by a failed job, never a running one
step docker network prune -f --filter until=1h     # networks without containers, old enough not to be a job still starting
step docker volume prune -f                        # anonymous volumes no container uses
step docker image prune -f                         # dangling images only: the service images (postgres, mariadb) stay cached
step docker builder prune -f --filter until=24h
# The checkout and the temp files of THIS instance's job; the tool cache (Python) stays.
find "$RUNNER_WORKSPACE" "$RUNNER_TEMP" -mindepth 1 -maxdepth 1 -exec rm -rf {} + \
  || { echo "job-completed: cleaning the workspace failed" >&2; status=1; }
exit $status
