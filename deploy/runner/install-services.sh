#!/bin/bash
# Run as ROOT on the runner machine. Installs one runner service per database job type (sqlite, pg, maria): its own
# directory /opt/actions-runner-<type>, its own registration (name maity-vm-<type>, label <prefix>-<type>), and the
# unit instance maity-runner@<type>. Needs: the runner user with rootless Docker, the hook in /opt/maity-runner-hooks,
# the runner package as a tarball, and a registration token from GitHub (Settings → Actions → Runners → New
# self-hosted runner; the token is valid for an hour and is not printed here).
# Usage: RUNNER_TOKEN=<token> RUNNER_TARBALL=/root/actions-runner-linux-x64-2.338.0.tar.gz \
#        [RUNNER_USER=gh-runner] [LABEL_PREFIX=maity-hub] [INSTANCES="sqlite pg maria"] install-services.sh
# Then run install-python.sh for each instance (README.md, step 5) and set the repository variable HUB_RUNNER_LABEL.
set -euo pipefail
RU=${RUNNER_USER:-gh-runner}
HOME_RU=${RUNNER_HOME:-$(getent passwd "$RU" | cut -d: -f6)}
PREFIX=${LABEL_PREFIX:-maity-hub}
INSTANCES=${INSTANCES:-sqlite pg maria}
URL=${RUNNER_URL:-https://github.com/oliver-zehentleitner/maity}
: "${RUNNER_TOKEN:?RUNNER_TOKEN is not set}" "${RUNNER_TARBALL:?RUNNER_TARBALL is not set}"
[ -f "$RUNNER_TARBALL" ] || { echo "no such tarball: $RUNNER_TARBALL" >&2; exit 1; }
HERE=$(cd "$(dirname "$0")" && pwd)
UID_RU=$(id -u "$RU")
[ -x /opt/maity-runner-hooks/job-completed.sh ] || install -d -m 755 /opt/maity-runner-hooks
install -m 755 -o root "$HERE/job-completed.sh" /opt/maity-runner-hooks/job-completed.sh
sed -e "s/<runner-user>/$RU/g" -e "s/<uid>/$UID_RU/g" "$HERE/maity-runner@.service" > /etc/systemd/system/maity-runner@.service

for t in $INSTANCES; do
  d=/opt/actions-runner-$t
  [ ! -e "$d/.runner" ] || { echo "$d is already registered; skipping (remove it first to redo)"; continue; }
  install -d "$d"
  tar xzf "$RUNNER_TARBALL" -C "$d"
  chown -R "$RU" "$d"
  # config.sh as the runner user (as root it refuses); the token is passed as an argument, never echoed.
  runuser -u "$RU" -- env HOME="$HOME_RU" "$d/config.sh" --url "$URL" --token "$RUNNER_TOKEN" --unattended --disableupdate \
    --name "maity-vm-$t" --labels "$PREFIX-$t" >/dev/null
  chown -R root:root "$d"
  chgrp "$RU" "$d/.runner" "$d/.credentials" "$d/.credentials_rsaparams"
  chmod 640 "$d/.runner" "$d/.credentials" "$d/.credentials_rsaparams"
  install -d -o "$RU" "$d/_work" "$d/_diag" "$d/_temp"
  echo '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' > "$d/.path"
  echo "registered maity-vm-$t with label $PREFIX-$t in $d"
done
systemctl daemon-reload
echo "installed: now run install-python.sh for each instance, then: systemctl enable --now maity-runner@<type>"
