# Rented servers as runners (a week, one to three machines)

For the database jobs of the CI on machines that do nothing else, instead of the maintainer's workstation. The steps are
the ones of [README.md](README.md), with the machine prepared by `bootstrap-server.sh`. The maintainer runs them; nothing
here is run before he says go. Each step names **who** (user, or the web page), **where**, and the **command**.

## One type per server

Three servers, one job type each: `pg`, `maria`, `sqlite`. Two services of different types on one machine would be fine
for the ports (each type binds its own), but each server then has its own uid, its own Docker and its own caps, and a
stalled machine takes down one type, not all. The first server runs **`maria`** (the slowest job, so the gain is the biggest
and the easiest to measure) on the dedicated profile below, with 8 pytest workers; add the next only after the first one
ran jobs without a stall. A server that runs two types is the same procedure with `INSTANCES="pg maria"`, one at a time.

The machine: Ubuntu 22.04 or 24.04, 8 vCPU, 16 GB, nothing else on it, SSH by key only, no other user, no secrets of the
project on it. The caps of [README.md](README.md) ("limits") are for a workstation and would throttle this machine to a fraction of itself
(150% CPU per service, `-n 2`). `dedicated-profile.sh` raises them to the size of the machine and keeps them as a fence: the service
may use 7 of 8 cores and 11 GB, everything the runner user runs 7.5 cores and 13 GB, no swap, so one core and about 3 GB stay for
the system and sshd.

## Steps (per server)

0. **Web, the repository** (Settings → Actions → General): "Fork pull request workflows" set to **require approval for all
   outside collaborators**. Once, before the first runner exists.
1. **Web, GitHub** (Settings → Actions → Runners → New self-hosted runner, Linux x64): copy the **tarball URL** and its
   **SHA-256** from the page, and the **registration token** (valid for an hour; it goes into the shell below, never into
   a chat or a file).
2. **root on the server**, any directory:
   `git clone https://github.com/oliver-zehentleitner/maity /root/maity && cd /root/maity && git checkout <sha>`
   (`<sha>`: the commit the ops agent names; the scripts are read at that commit, not at whatever `main` is later).
3. **root, `/root/maity/deploy/runner`:** `./bootstrap-server.sh`. It ends with `ok:` or with a `FAIL:` line (stop and
   report that line).
4. **root, `/root`:** `curl -fsSLO <tarball-url> && echo "<sha256>  $(basename <tarball-url>)" | sha256sum -c`. It must
   print `OK`.
5. **root, `/root/maity/deploy/runner`:** `RUNNER_TOKEN=<token> RUNNER_TARBALL=/root/<tarball-name> INSTANCES=<type> ./install-services.sh`
   (`<type>`: `maria` on the first server), then `RUNNER_DIR=/opt/actions-runner-<type> SERVICE=maity-runner@<type> ./install-python.sh`.
6. **root, same directory:** `./dedicated-profile.sh <type>`. It refuses on a machine that is not exactly 8 cores and 16 GB, and prints the
   values it set.
7. **root:** `systemctl enable --now maity-runner@<type>`; GitHub shows the runner as **Idle**. Then check the caps before any job:
   - `systemctl show -p ControlGroup maity-runner@<type>`: it must end under `user-<uid>.slice` (`<uid>`: `id -u gh-runner`).
   - `systemctl show -p CPUQuotaPerSecUSec -p MemoryMax user-<uid>.slice`: `7.5s` and `13958643712`.
   - `systemctl show -p CPUQuotaPerSecUSec -p MemoryMax maity-runner@<type>`: `7s` and `11811160064`.
   - `systemctl show -p Environment maity-runner@<type>`: it ends with `PYTEST_ARGS=-n 8`.
8. **root, a second shell, kept open:** `vmstat 5`. **Web, the repository variables** (Settings → Secrets and variables →
   Actions → Variables): `HUB_RUNNER_TYPES` = `<type>` first, then `HUB_RUNNER_LABEL` = `maity-hub`. Only the job of that type goes to
   the machine; the other two stay hosted. Watch `vmstat` (`id` above 10, `wa` low, `si`/`so` zero) while the first job runs.
9. **Taking a server away:** delete `HUB_RUNNER_LABEL` (and `HUB_RUNNER_TYPES`) first, **cancel and rerun** the runs still queued on its label
   (deleting the variable does not re-route them), then remove the runner (Settings → Actions → Runners) and delete the server.
   A server a fork's job may have run on is deleted, not cleaned.

## What the bootstrap does and what it does not

It installs Docker from Docker's own repository (the key file must hold exactly one key and its fingerprint is checked, the script stops otherwise),
switches the system Docker off, creates `gh-runner` without a password or sudo, turns on lingering, installs rootless
Docker for it, allows `rootlesskit` the user namespaces Ubuntu 24.04 denies by default, and installs a firewall chain
`MAITY_RUNNER` for that uid (IPv4 and IPv6, rebuilt at boot by `maity-runner-firewall.service`, which starts before the user manager of
the runner user; `install-services.sh` makes the runner units require it and start after it, so a failed rule set stops the runner). It then tests what it built: the user cannot `sudo`,
cannot reach `127.0.0.1:22`, `[::1]:22`, its own public address on port 22 or `169.254.169.254`, gets answers from a listener of its own
on the database ports 5432 and 3306 (the path of a job to its service container), and can reach `github.com`.

It does not harden SSH, set up updates or watch the machine: the provider's image and Ubuntu's unattended upgrades are what
there is for a week. It was written without a fresh machine to run it on; the first server is its first run, and a `FAIL`
there is a bug to fix in the script, not a reason to loosen a check.
