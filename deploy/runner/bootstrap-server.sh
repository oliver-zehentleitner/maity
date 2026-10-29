#!/bin/bash
# Run as ROOT, once, on a FRESH Ubuntu 22.04/24.04 server that does nothing else (a rented one for the runner). It prepares
# step 1 of the README "Install": the runner user, rootless Docker for it, lingering, and the firewall rules that keep that
# user away from the machine's own services and the provider's internal network. It installs no runner (install-services.sh
# does) and registers nothing. Nothing here is printed that is secret; there is nothing secret in it.
# Usage: bootstrap-server.sh        [RUNNER_USER=gh-runner]
# Not for a machine that already has a runner user or a Docker of its own: it stops there.
set -euo pipefail
RU=${RUNNER_USER:-gh-runner}
[ "$(id -u)" = 0 ] || { echo "run as root" >&2; exit 1; }
. /etc/os-release
case "${ID:-}-${VERSION_ID:-}" in ubuntu-22.04|ubuntu-24.04) ;; *) echo "Ubuntu 22.04 or 24.04 only (this is ${PRETTY_NAME:-unknown})" >&2; exit 1 ;; esac
if id "$RU" >/dev/null 2>&1; then echo "user $RU exists; this script is for a fresh server only" >&2; exit 1; fi
if command -v docker >/dev/null 2>&1; then echo "docker is installed already; this script is for a fresh server only" >&2; exit 1; fi
cd /
echo "machine: $(nproc) vCPU, $(awk '/MemTotal/ {printf "%.1f", $2/1048576}' /proc/meminfo) GB RAM, $(df -h --output=avail / | tail -1 | tr -d ' ') free on /"

# --- 1. packages: rootless Docker needs uidmap, a user bus and a user-space network stack ---------------------------------
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq ca-certificates curl gnupg uidmap dbus-user-session slirp4netns iptables python3 >/dev/null
# Docker's own apt repository (Ubuntu's docker.io has no rootless installer). The key must be Docker's: its fingerprint is
# checked here and the script stops on any other.
install -d -m 755 /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
fpr=$(gpg --show-keys --with-colons /etc/apt/keyrings/docker.asc | awk -F: '/^fpr:/ {print $10; exit}')
[ "$fpr" = "9DC858229FC7DD38854AE2D88D81803C0EBFCD88" ] || { echo "unexpected Docker key fingerprint: $fpr" >&2; rm -f /etc/apt/keyrings/docker.asc; exit 1; }
chmod 644 /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq
apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-ce-rootless-extras >/dev/null
# The system Docker (root, the docker group) is not wanted: only the rootless one of the runner user.
systemctl disable --now docker.service docker.socket containerd.service >/dev/null 2>&1 || true

# --- 2. Ubuntu 24.04 stops unprivileged user namespaces by default (AppArmor); rootlesskit is allowed that, nothing else ---
if [ "$(sysctl -n kernel.apparmor_restrict_unprivileged_userns 2>/dev/null || echo 0)" = 1 ] && [ -d /etc/apparmor.d ]; then
  cat > /etc/apparmor.d/usr.bin.rootlesskit <<'EOF'
abi <abi/4.0>,
include <tunables/global>
/usr/bin/rootlesskit flags=(unconfined) {
  userns,
  include if exists <local/usr.bin.rootlesskit>
}
EOF
  apparmor_parser -r /etc/apparmor.d/usr.bin.rootlesskit
fi

# --- 3. the runner user: no sudo, no password, lingering so its Docker keeps running ---------------------------------------
useradd --create-home --shell /bin/bash "$RU"
passwd -l "$RU" >/dev/null
UID_RU=$(id -u "$RU")
grep -q "^$RU:" /etc/subuid || usermod --add-subuids 100000-165535 "$RU"
grep -q "^$RU:" /etc/subgid || usermod --add-subgids 100000-165535 "$RU"
loginctl enable-linger "$RU"
for _ in $(seq 1 30); do [ -S "/run/user/$UID_RU/bus" ] && break; sleep 1; done
[ -S "/run/user/$UID_RU/bus" ] || { echo "the systemd user manager of $RU did not start" >&2; exit 1; }

# --- 4. rootless Docker for that user -------------------------------------------------------------------------------------
as_ru() { runuser -u "$RU" -- env HOME="/home/$RU" XDG_RUNTIME_DIR="/run/user/$UID_RU" \
  DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$UID_RU/bus" PATH="/usr/bin:/usr/local/bin:/usr/sbin:/bin" "$@"; }
as_ru dockerd-rootless-setuptool.sh install >/dev/null
for _ in $(seq 1 30); do [ -S "/run/user/$UID_RU/docker.sock" ] && break; sleep 1; done
as_ru env DOCKER_HOST="unix:///run/user/$UID_RU/docker.sock" docker info --format '{{.SecurityOptions}}' | grep -q rootless \
  || { echo "the Docker of $RU is not rootless" >&2; exit 1; }

# --- 5. the firewall: the runner user reaches the internet, not the machine's own services or an internal network ------------
# Everything its jobs start (the rootless Docker, the containers behind slirp4netns) runs under its uid. Allowed first: the
# two database ports of the jobs' service containers on loopback, and the local resolver. A chain of its own, rebuilt at boot.
cat > /usr/local/sbin/maity-runner-firewall.sh <<EOF
#!/bin/bash
# Written by bootstrap-server.sh. Rejects, for uid $UID_RU, loopback and the machine's own addresses (except replies, the database ports and the resolver), the private
# ranges, link-local (the provider's metadata service is 169.254.169.254) and shared address space.
set -eu
for ipt in iptables ip6tables; do
  \$ipt -N MAITY_RUNNER 2>/dev/null || \$ipt -F MAITY_RUNNER
  \$ipt -C OUTPUT -m owner --uid-owner $UID_RU -j MAITY_RUNNER 2>/dev/null || \$ipt -I OUTPUT 1 -m owner --uid-owner $UID_RU -j MAITY_RUNNER
done
# Answers first: the reply of a listener of this uid (rootlesskit on 127.0.0.1:5432) is a packet of this uid to a loopback
# address, and would meet the REJECT below. Only packets of a connection that already exists; a new one is judged by the rules after.
for ipt in iptables ip6tables; do
  \$ipt -A MAITY_RUNNER -m conntrack --ctstate ESTABLISHED,RELATED -j RETURN
done
for port in 5432 3306; do
  iptables  -A MAITY_RUNNER -o lo -d 127.0.0.1 -p tcp --dport \$port -j RETURN
  ip6tables -A MAITY_RUNNER -o lo -d ::1 -p tcp --dport \$port -j RETURN
done
iptables -A MAITY_RUNNER -o lo -d 127.0.0.53 -p udp --dport 53 -j RETURN
iptables -A MAITY_RUNNER -o lo -d 127.0.0.53 -p tcp --dport 53 -j RETURN
# Anything else on loopback is rejected, the machine's own public address included (it is routed over lo): sshd on 0.0.0.0:22.
iptables  -A MAITY_RUNNER -o lo -j REJECT
ip6tables -A MAITY_RUNNER -o lo -j REJECT
iptables  -A MAITY_RUNNER -d 127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16,100.64.0.0/10 -j REJECT
ip6tables -A MAITY_RUNNER -d ::1/128,fc00::/7,fe80::/10 -j REJECT
EOF
chmod 755 /usr/local/sbin/maity-runner-firewall.sh
cat > /etc/systemd/system/maity-runner-firewall.service <<'EOF'
[Unit]
Description=Firewall rules for the runner user (maity)
After=network.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/maity-runner-firewall.sh

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now maity-runner-firewall.service >/dev/null

# --- 6. check what was just built, loudly ---------------------------------------------------------------------------------
fail=0
# the user must not become root, and must not reach loopback services or the metadata address
if runuser -u "$RU" -- sudo -n true 2>/dev/null; then echo "FAIL: $RU can sudo" >&2; fail=1; fi
if runuser -u "$RU" -- bash -c 'exec 3<>/dev/tcp/127.0.0.1/22' 2>/dev/null; then echo "FAIL: $RU reaches 127.0.0.1:22" >&2; fail=1; fi
if runuser -u "$RU" -- curl -sS -m 4 -o /dev/null http://169.254.169.254/ 2>/dev/null; then echo "FAIL: $RU reaches 169.254.169.254" >&2; fail=1; fi
# the jobs' own path must work: a listener of the runner user on a database port answers a client of the same user (the
# replies are packets of that uid to loopback; the first version of the chain rejected them)
for port in 5432 3306; do
  runuser -u "$RU" -- python3 - "$port" <<'PY' &
import socket, sys
s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(("127.0.0.1", int(sys.argv[1]))); s.listen(1); s.settimeout(6)
try:
    c, _ = s.accept(); c.sendall(b"hello"); c.close()
except Exception:
    pass
PY
  sleep 1
  got=$(runuser -u "$RU" -- timeout 4 bash -c "exec 3<>/dev/tcp/127.0.0.1/$port; read -t 3 -u 3 l; echo \$l" 2>/dev/null || true)
  wait
  [ "$got" = hello ] || { echo "FAIL: $RU gets no answer from a listener of its own on 127.0.0.1:$port" >&2; fail=1; }
done
# the machine's own public address is routed over loopback: sshd on 0.0.0.0:22 must stay out of reach as well
own=$(ip -4 route get 1.1.1.1 2>/dev/null | awk '{for (i=1; i<NF; i++) if ($i == "src") {print $(i+1); exit}}')
if [ -n "$own" ] && runuser -u "$RU" -- bash -c "exec 3<>/dev/tcp/$own/22" 2>/dev/null; then echo "FAIL: $RU reaches $own:22 (the machine's own address)" >&2; fail=1; fi
# outbound to the internet and the resolver must still work (the runner downloads, uv installs Python)
runuser -u "$RU" -- curl -fsS -m 10 -o /dev/null https://github.com || { echo "FAIL: $RU cannot reach github.com (resolver or firewall)" >&2; fail=1; }
[ "$fail" = 0 ] || exit 1
echo "ok: $RU (uid $UID_RU) with rootless Docker and the firewall chain MAITY_RUNNER."
echo "next: SERVER-SETUP.md step 4 (download the runner), then install-services.sh and install-python.sh."
