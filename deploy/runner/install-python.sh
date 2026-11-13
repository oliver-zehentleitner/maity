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
#        (FORCE=1 restarts the service even while a job runs; UV_VERSION and UV_SHA256 pin uv: a different version
#        needs the sha256 of its uv-x86_64-unknown-linux-gnu.tar.gz from the release's checksums)
# uv comes from its release tarball, checked against UV_SHA256 before anything in it runs; no installer script is
# piped into a shell.
set -euo pipefail
cd /   # a neutral directory: uv looks for a config in the current one, which the runner user may not read (/root)
RU=${RUNNER_USER:-gh-runner}
HOME_RU=${RUNNER_HOME:-$(getent passwd "$RU" | cut -d: -f6)}
RUNNER_DIR=${RUNNER_DIR:-/opt/actions-runner}
SERVICE=${SERVICE:-maity-runner}
SERIES=${PYTHON_SERIES:-3.12}
UV_VERSION=${UV_VERSION:-0.13.6}
# The sha256 of uv-x86_64-unknown-linux-gnu.tar.gz of uv 0.13.6, from the release's
# uv-x86_64-unknown-linux-gnu.tar.gz.sha256 (github.com/astral-sh/uv/releases/tag/0.13.6).
UV_SHA256=${UV_SHA256:-f29c3e94ffabd7e6f3ba521dba169a9b7ec12100bf3257087f0f24f6123f3645}
UV_TARGET=uv-x86_64-unknown-linux-gnu
TOOL=$RUNNER_DIR/_work/_tool
as_ru() { runuser -u "$RU" -- env HOME="$HOME_RU" PATH="$HOME_RU/.local/bin:/usr/local/bin:/usr/bin:/bin" UV_PYTHON_PREFERENCE=only-managed "$@"; }

if pgrep -u "$RU" -f Runner.Worker >/dev/null && [ -z "${FORCE:-}" ]; then
  echo "a job is running on the runner; the service restart at the end would cancel it. Wait for an empty queue or set FORCE=1." >&2
  exit 1
fi

if [ ! -x "$HOME_RU/.local/bin/uv" ]; then
  [ "$(uname -m)" = x86_64 ] || { echo "uv is pinned for x86_64 only; this machine is $(uname -m)" >&2; exit 1; }
  case "$UV_SHA256" in
    *[!0-9a-f]*|'') echo "UV_SHA256 is not a sha256 ('$UV_SHA256'): set the checksum of $UV_TARGET.tar.gz for uv $UV_VERSION" >&2; exit 1;;
  esac
  [ "${#UV_SHA256}" = 64 ] || { echo "UV_SHA256 must be 64 hex digits" >&2; exit 1; }
  # As the runner user, in a directory of its own: download, check, and only then unpack and install.
  as_ru sh -c '
    set -eu
    t=$(mktemp -d); trap "rm -rf \"\$t\"" EXIT
    curl -fsSL -o "$t/uv.tar.gz" "https://github.com/astral-sh/uv/releases/download/$1/$3.tar.gz"
    echo "$2  $t/uv.tar.gz" | sha256sum -c --quiet -
    tar -xzf "$t/uv.tar.gz" -C "$t"
    install -d "$HOME/.local/bin"
    install -m 0755 "$t/$3/uv" "$t/$3/uvx" "$HOME/.local/bin/"
  ' sh "$UV_VERSION" "$UV_SHA256" "$UV_TARGET"
fi
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
