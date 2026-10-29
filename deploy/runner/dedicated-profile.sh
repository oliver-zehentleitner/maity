#!/bin/bash
# Run as ROOT on a DEDICATED runner server (8 cores, 16 GB, nothing else on it: SERVER-SETUP.md), after install-services.sh.
# The caps of maity-runner@.service are for the maintainer's workstation (150% CPU, -n 2, slice 400% / 8 GB); with them a
# dedicated machine would measure nothing. This writes drop-ins that raise them to the size of the machine and keeps them as a
# fence against a runaway job: one core and about 3 GB stay for the system and sshd. It never edits the template.
# Usage: [RUNNER_USER=gh-runner] [WORKERS=8] dedicated-profile.sh <type> [<type> ...]     (type: sqlite, pg or maria)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
[ "$#" -ge 1 ] || { echo "usage: dedicated-profile.sh <type> [<type> ...]" >&2; exit 1; }
RU=${RUNNER_USER:-gh-runner}
WORKERS=${WORKERS:-8}
CORES=$(nproc)
MEM_KB=$(awk '/MemTotal/ {print $2}' /proc/meminfo)
# Only for the size this was written for: eight cores and 16 GB (MemTotal reads a little under 16 GB).
if [ "$CORES" -lt 8 ] || [ "$MEM_KB" -lt 15000000 ]; then
  echo "this is for 8 cores and 16 GB; this machine has $CORES cores and $((MEM_KB / 1024)) MB. Not applied." >&2
  exit 1
fi
UID_RU=$(id -u "$RU")
CPU_SERVICE=$(( (CORES - 1) * 100 ))     # one core stays free
CPU_SLICE=$(( CORES * 100 - 50 ))
for t in "$@"; do
  case "$t" in sqlite|pg|maria) ;; *) echo "unknown type: $t" >&2; exit 1 ;; esac
  [ -f "/etc/systemd/system/maity-runner@.service" ] || { echo "maity-runner@.service is not installed; run install-services.sh first" >&2; exit 1; }
  d=/etc/systemd/system/maity-runner@$t.service.d
  install -d "$d"
  cat > "$d/dedicated.conf" <<UNIT
[Service]
CPUQuota=${CPU_SERVICE}%
MemoryMax=11G
Environment="PYTEST_ARGS=-n ${WORKERS}"
UNIT
done
d=/etc/systemd/system/user-$UID_RU.slice.d
install -d "$d"
# A later file name wins over maity-runner-limits.conf (the workstation values from install-services.sh).
cat > "$d/zz-dedicated.conf" <<UNIT
[Slice]
CPUQuota=${CPU_SLICE}%
MemoryMax=13G
UNIT
systemctl daemon-reload
for t in "$@"; do
  echo "maity-runner@$t: $(systemctl show -p CPUQuotaPerSecUSec -p MemoryMax maity-runner@$t | tr '\n' ' ') PYTEST_ARGS=-n ${WORKERS}"
done
echo "user-$UID_RU.slice: $(systemctl show -p CPUQuotaPerSecUSec -p MemoryMax user-$UID_RU.slice | tr '\n' ' ')"
echo "a running service picks the values up at its next start: systemctl restart maity-runner@<type> (with no job running)"
