#!/bin/bash
# Run as ROOT on the runner machine, after the runner is installed (README.md), when no job is running.
#
# GitHub's setup-python knows Ubuntu, macOS and Windows only: on Debian it ends with "The version '3.12' with
# architecture 'x64' was not found". This installs Python with uv as the runner user and links it where setup-python
# looks first, the runner's tool cache (<runner dir>/_work/_tool/Python/<version>/x64). Also:
#  - uv's standalone Python is marked "externally managed" (PEP 668), which makes `pip install` fail in the jobs
#    ("error: externally-managed-environment"). This copy belongs to the runner alone, so the marker is removed.
#  - config.sh stored the PATH of the shell that ran it; `.path` is replaced by a plain one (root's PATH can hold
#    directories the runner user may not enter, e.g. /root/.nvm).
# Everything inside the runner user's own paths (its home, `_work/_tool`) is done AS the runner user: a job can leave
# symlinks there, and root following one would write wherever it points. Root only writes `.path` (root-owned) and
# restarts the service.
# Usage: RUNNER_DIR=/opt/actions-runner-pg SERVICE=maity-runner@pg [RUNNER_USER=gh-runner] [RUNNER_HOME=...] \
#        [PYTHON_SERIES=3.12] install-python.sh      (once per runner directory)
#        (FORCE=1 restarts the service even while a job runs; UV_VERSION pins the uv installer)
set -euo pipefail
cd /   # a neutral directory: uv looks for a config in the current one, which the runner user may not read (/root)
RU=${RUNNER_USER:-gh-runner}
HOME_RU=${RUNNER_HOME:-$(getent passwd "$RU" | cut -d: -f6)}
RUNNER_DIR=${RUNNER_DIR:-/opt/actions-runner}
SERVICE=${SERVICE:-maity-runner}
SERIES=${PYTHON_SERIES:-3.12}
UV_VERSION=${UV_VERSION:-0.13.6}
TOOL=$RUNNER_DIR/_work/_tool
as_ru() { runuser -u "$RU" -- env HOME="$HOME_RU" PATH="$HOME_RU/.local/bin:/usr/local/bin:/usr/bin:/bin" UV_PYTHON_PREFERENCE=only-managed "$@"; }

if pgrep -u "$RU" -f Runner.Worker >/dev/null && [ -z "${FORCE:-}" ]; then
  echo "a job is running on the runner; the service restart at the end would cancel it. Wait for an empty queue or set FORCE=1." >&2
  exit 1
fi

[ -x "$HOME_RU/.local/bin/uv" ] || as_ru sh -c "curl -LsSf https://astral.sh/uv/$UV_VERSION/install.sh | sh"
as_ru uv python install "$SERIES"
PY=$(as_ru uv python find "$SERIES")                       # UV_PYTHON_PREFERENCE=only-managed (in as_ru) limits it to uv-managed Pythons;
#                                                              # the flag --managed-python cannot be combined with that setting; .../cpython-3.12.X-linux-x86_64-gnu/bin/python3.12
ROOT=$(as_ru sh -c 'dirname "$(dirname "$(readlink -f "$1")")"' sh "$PY")
case "$ROOT" in "$HOME_RU"/.local/share/uv/python/*) ;; *) echo "refusing: $ROOT is not a uv-managed Python under $HOME_RU" >&2; exit 1;; esac
VER=$(as_ru "$PY" -c 'import platform; print(platform.python_version())')
echo "python $VER at $ROOT"
as_ru install -d "$TOOL/Python/$VER"
as_ru ln -sfn "$ROOT" "$TOOL/Python/$VER/x64"
as_ru touch "$TOOL/Python/$VER/x64.complete"
as_ru sh -c 'rm -f "$1"/lib/python3.*/EXTERNALLY-MANAGED' sh "$ROOT"
as_ru "$TOOL/Python/$VER/x64/bin/python3" -m pip --version
echo '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' > "$RUNNER_DIR/.path"
systemctl try-restart "$SERVICE"   # restarts a running service only; starting is a deliberate step (README)
echo "done: python $VER is in the tool cache (a running $SERVICE was restarted)"
