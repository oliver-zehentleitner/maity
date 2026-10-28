#!/bin/bash
# Run as ROOT on the runner machine, after the runner is installed (README.md).
#
# GitHub's setup-python knows Ubuntu, macOS and Windows only: on Debian it ends with "The version '3.12' with
# architecture 'x64' was not found". This installs Python with uv as the runner user and links it where setup-python
# looks first, the runner's tool cache (<runner dir>/_work/_tool/Python/<version>/x64). Also:
#  - uv's standalone Python is marked "externally managed" (PEP 668), which makes `pip install` fail in the jobs
#    ("error: externally-managed-environment"). This copy belongs to the runner alone, so the marker is removed.
#  - config.sh stored the PATH of the shell that ran it; `.path` is replaced by a plain one (root's PATH can hold
#    directories the runner user may not enter, e.g. /root/.nvm).
# Usage: RUNNER_USER=gh-runner RUNNER_HOME=/workspace/gh-runner PYTHON_SERIES=3.12 install-python.sh
set -euo pipefail
RU=${RUNNER_USER:-gh-runner}
HOME_RU=${RUNNER_HOME:-$(getent passwd "$RU" | cut -d: -f6)}
RUNNER_DIR=${RUNNER_DIR:-/opt/actions-runner}
SERIES=${PYTHON_SERIES:-3.12}
TOOL=$RUNNER_DIR/_work/_tool
as_ru() { runuser -u "$RU" -- env HOME="$HOME_RU" PATH="$HOME_RU/.local/bin:/usr/local/bin:/usr/bin:/bin" "$@"; }

[ -x "$HOME_RU/.local/bin/uv" ] || as_ru sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
as_ru uv python install "$SERIES"
PY=$(as_ru uv python find "$SERIES")                  # .../cpython-3.12.X-linux-x86_64-gnu/bin/python3.12
ROOT=$(dirname "$(dirname "$(readlink -f "$PY")")")   # .../cpython-3.12.X-linux-x86_64-gnu
VER=$(as_ru "$PY" -c 'import platform; print(platform.python_version())')
echo "python $VER at $ROOT"
install -d -o "$RU" "$TOOL" "$TOOL/Python" "$TOOL/Python/$VER"
ln -sfn "$ROOT" "$TOOL/Python/$VER/x64"
touch "$TOOL/Python/$VER/x64.complete"
chown -h "$RU" "$TOOL/Python/$VER/x64" "$TOOL/Python/$VER/x64.complete"
rm -f "$ROOT"/lib/python3.*/EXTERNALLY-MANAGED
as_ru "$TOOL/Python/$VER/x64/bin/python3" -m pip --version
echo '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' > "$RUNNER_DIR/.path"
systemctl restart maity-runner
echo "done: python $VER is in the tool cache, runner restarted"
