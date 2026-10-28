#!/bin/bash
# Run as ROOT on the runner machine. Installs one runner service per database job type (sqlite, pg, maria): its own
# directory /opt/actions-runner-<type>, its own registration (name maity-vm-<type>, label <prefix>-<type>), and the
# unit instance maity-runner@<type>. Needs: the runner user with rootless Docker, the hook in /opt/maity-runner-hooks,
# the runner package as a tarball, and a registration token from GitHub (Settings → Actions → Runners → New
# self-hosted runner; the token is valid for an hour and is not printed here).
# Start with ONE instance (INSTANCES=pg) while someone watches the machine, then add the others (README, "limits").
# Usage: RUNNER_TOKEN=<token> RUNNER_TARBALL=/root/actions-runner-linux-x64-2.338.0.tar.gz \
#        [RUNNER_USER=gh-runner] [LABEL_PREFIX=maity-hub] [INSTANCES="sqlite pg maria"] install-services.sh
# Then run install-python.sh for each instance (README.md, step 4) and set the repository variable HUB_RUNNER_LABEL.
set -euo pipefail
RU=${RUNNER_USER:-gh-runner}
HOME_RU=${RUNNER_HOME:-$(getent passwd "$RU" | cut -d: -f6)}
PREFIX=${LABEL_PREFIX:-maity-hub}
INSTANCES=${INSTANCES:-sqlite pg maria}
URL=${RUNNER_URL:-https://github.com/oliver-zehentleitner/maity}
: "${RUNNER_TOKEN:?RUNNER_TOKEN is not set}" "${RUNNER_TARBALL:?RUNNER_TARBALL is not set}"
[ -f "$RUNNER_TARBALL" ] || { echo "no such tarball: $RUNNER_TARBALL" >&2; exit 1; }
# Root works in directories that belong to the runner user for a moment (config.sh runs as that user). A process of that
# user could leave a symlink there that a root chgrp, chmod or redirect would follow. So no runner of that user may run:
# stop every maity-runner* service first (README, step 0).
if pgrep -u "$RU" -f 'Runner\.(Listener|Worker)|runsvc\.sh' >/dev/null; then
  echo "a runner of $RU is running; stop all runner services first: systemctl stop 'maity-runner*'" >&2
  exit 1
fi
HERE=$(cd "$(dirname "$0")" && pwd)
UID_RU=$(id -u "$RU")
[ -x /opt/maity-runner-hooks/job-completed.sh ] || install -d -m 755 /opt/maity-runner-hooks
install -m 755 -o root "$HERE/job-completed.sh" /opt/maity-runner-hooks/job-completed.sh
sed -e "s/<runner-user>/$RU/g" -e "s/<uid>/$UID_RU/g" "$HERE/maity-runner@.service" > /etc/systemd/system/maity-runner@.service
# One cap for everything the runner user runs, rootless Docker included (README, "Limits").
install -d "/etc/systemd/system/user-$UID_RU.slice.d"
install -m 644 "$HERE/user-slice-limits.conf" "/etc/systemd/system/user-$UID_RU.slice.d/maity-runner-limits.conf"

# A service container left running by a job that was cut off when the services stopped (they run under the runner
# user's Docker, outside the unit's cgroup) would keep 127.0.0.1:5432 or :3306 for good: each registration is new, so
# no runner knows its label any more. Refuse until none is left.
left=$(runuser -u "$RU" -- env XDG_RUNTIME_DIR="/run/user/$UID_RU" DOCKER_HOST="unix:///run/user/$UID_RU/docker.sock" docker ps -q 2>/dev/null || true)
if [ -n "$left" ]; then
  echo "containers are still running in the Docker of $RU; remove them first (docker rm -f \$(docker ps -q) as $RU) and run again" >&2
  exit 1
fi

for t in $INSTANCES; do
  d=/opt/actions-runner-$t
  # Never reuse a directory: one left by a failed run belongs to the runner user and may hold symlinks.
  if [ -e "$d" ] || [ -L "$d" ]; then echo "$d exists; remove it (rm -rf $d, after stopping maity-runner@$t) and run again, skipping $t" >&2; continue; fi
  install -d "$d"
  tar xzf "$RUNNER_TARBALL" -C "$d"
  chown -R "$RU" "$d"
  # config.sh as the runner user (as root it refuses); the token is passed as an argument, never echoed.
  runuser -u "$RU" -- env HOME="$HOME_RU" "$d/config.sh" --url "$URL" --token "$RUNNER_TOKEN" --unattended --disableupdate \
    --name "maity-vm-$t" --labels "$PREFIX-$t" >/dev/null
  chown -R root:root "$d"
  # Only regular files are handed on: a symlink among the registration files stops the script.
  for f in .runner .credentials .credentials_rsaparams; do
    [ -f "$d/$f" ] && [ ! -L "$d/$f" ] || { echo "$d/$f is missing or a symlink; stopping, remove $d and run again" >&2; exit 1; }
  done
  chgrp "$RU" "$d/.runner" "$d/.credentials" "$d/.credentials_rsaparams"
  chmod 640 "$d/.runner" "$d/.credentials" "$d/.credentials_rsaparams"
  # $d is root's now, nothing of the runner user can appear in it any more; whatever _work, _diag and _temp hold (a
  # symlink among it) is removed, never followed, and they are created again for the runner user.
  rm -rf "$d/_work" "$d/_diag" "$d/_temp"
  install -d -o "$RU" "$d/_work" "$d/_diag" "$d/_temp"
  rm -f "$d/.path"
  echo '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' > "$d/.path"
  echo "registered maity-vm-$t with label $PREFIX-$t in $d"
done
systemctl daemon-reload
echo "installed: now run install-python.sh for each instance, then: systemctl enable --now maity-runner@<type>"
