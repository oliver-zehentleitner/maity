#!/bin/bash
# ACTIONS_RUNNER_HOOK_JOB_COMPLETED: leave nothing of a job behind for the next one.
# Runs as the runner's own user; its Docker is the rootless one of that user.
set -u
docker ps -aq | xargs -r docker rm -f >/dev/null 2>&1
docker network prune -f >/dev/null 2>&1
docker volume prune -f >/dev/null 2>&1
# The checkout and the temp files of the job; the tool cache (Python) stays.
rm -rf "${RUNNER_WORKSPACE:?}"/* "${RUNNER_TEMP:?}"/* 2>/dev/null
exit 0
