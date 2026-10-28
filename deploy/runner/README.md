# Self-hosted runner for the database jobs

The three hub jobs that run the whole suite against a database (`hub-sqlite`,
`hub-postgresql`, `hub-mariadb` in `.github/workflows/ci.yml`) may run on a machine
of the maintainer's instead of a GitHub-hosted runner. Everything else stays hosted.

## Which runner a job gets

`ci.yml` reads the repository variable `HUB_RUNNER` (Settings → Secrets and variables →
Actions → Variables): the runner labels as JSON, for example
`["self-hosted","maity-hub"]`.

- Variable unset or empty: GitHub-hosted (`ubuntu-latest`). **Deleting the variable is the
  whole fallback**, no commit needed.
- Set: pushes to `main` and pull requests from this repository use the runner; the
  condition sends pull requests from forks to the hosted runners.

## The trust boundary, stated honestly

**The condition in `ci.yml` is not a protection against a fork.** A pull request from a
fork runs the `ci.yml` of the fork's merge commit; the fork can write
`runs-on: [self-hosted, maity-hub]` itself. What keeps a fork's code off the machine is
the repository setting, and nothing else:

- Settings → Actions → General → "Fork pull request workflows": **require approval for all
  outside collaborators**. Every "Approve and run" on a fork pull request puts that code on
  the machine. Before approving, read the diff, `.github/` above all; never approve a fork
  pull request that touches `.github/`.
- No workflow of this repository uses `pull_request_target`, `workflow_run` or a label
  trigger; keep it so.
- "Only code of this repository" means every branch of everyone with push access to the
  repository, agents included.

After a malicious job the machine is reinstalled; the hook below cannot make it clean.

## What the machine must be

- A user of its own with no `sudo`, no group of the people who work on the machine, and no
  read access to their homes (`sudo -u <runner-user> ls /home/<other>` must fail). No
  deploy keys, kubeconfig or tokens of the project anywhere that user can read.
- The runner lives outside the runner user's home and is owned by root:
  `/opt/actions-runner` (with `run.sh`, `bin/`, the registration files `.runner` and
  `.credentials*`), the hook in `/opt/maity-runner-hooks/` (not inside the runner's own
  directory, which GitHub's documentation advises against), and the unit in
  `/etc/systemd/system/`. The runner user owns only `/opt/actions-runner/_work`, `_diag` and
  `_temp` (and its Docker data under its home). A job that could rewrite the hook, `run.sh` or
  the unit would take over every later job, and in the runner user's own home it could
  rename a directory and put its own in the place, or override a user unit through its own
  systemd manager. That is why the unit is a system unit with `User=<runner-user>`.
- Rootless Docker for that user (`dockerd-rootless-setuptool.sh install`): the jobs'
  `services:` (PostgreSQL, MariaDB) need a Docker API, and the Docker group would be root.
  The services bind to `127.0.0.1` only, with their images pinned by digest in `ci.yml`.
- A firewall rule per user that keeps the runner user away from local services and the
  internal network, IPv4 and IPv6, for example
  `iptables -A OUTPUT -m owner --uid-owner <uid> -d 127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,169.254.0.0/16 -j REJECT`
  and `ip6tables -A OUTPUT -m owner --uid-owner <uid> -d ::1/128,fc00::/7,fe80::/10 -j REJECT`,
  with the loopback ports of its own Docker services allowed first.
- Lingering keeps the runner user's systemd user manager running. `KillMode=control-group`
  does nothing against a process a job starts there (`systemd-run --user`, a unit under
  `~/.config/systemd/user`): it lives outside the unit's cgroup, under the same uid, and can
  read the environment of later jobs. That is one more reason for "reinstall after a malicious
  job", and lingering is there only for the rootless Docker.
- The tool cache (Python from `setup-python`) is kept between jobs and is writable for the
  runner user: a job can replace it for the later ones. That is part of the boundary above.

## Install

1. Create the user (`<runner-user>`, uid `<uid>`), enable lingering, install rootless Docker
   for it (see above).
2. On GitHub: Settings → Actions → Runners → New self-hosted runner (Linux x64). As root,
   unpack it to `/opt/actions-runner` and `chown -R <runner-user> /opt/actions-runner`. Run
   `config.sh --url <repo> --labels maity-hub --unattended --disableupdate` **as the runner
   user**, with the registration token from that page (as root it refuses: "Must not run with
   sudo"). The runner's self-update would write into its own directory, which the runner user
   may not; update it by hand, as root, when GitHub asks for a newer version. Then hand the
   files over: `chown -R root:root /opt/actions-runner`, then `cd /opt/actions-runner`; the
   runner user still has to read its registration, so `chgrp <runner-user> .runner
   .credentials .credentials_rsaparams` (this assumes a group of the same name as the user,
   the default on Debian and Ubuntu; otherwise use the user's primary group) and `chmod 640`
   on those three files (a root-owned 0600 `.credentials_rsaparams` stops the runner from
   starting); finally `install -d -o <runner-user> _work _diag _temp`.
3. Put `job-completed.sh` into `/opt/maity-runner-hooks/` (root-owned, executable) and
   `maity-runner.service` into `/etc/systemd/system/` with `<runner-user>` and `<uid>` filled
   in, then `systemctl enable --now maity-runner`. The unit starts `bin/runsvc.sh`, not `run.sh` (which writes into the runner's directory), and
   uses `KillMode=control-group`.
   The hook's output is shown in the job log (step "Complete runner"), which anyone can
   read in a public repository.
4. Set `HUB_RUNNER` to `["self-hosted","maity-hub"]`, and the fork-approval setting above.

## Why not an ephemeral runner

An ephemeral runner registers per job, which needs a repository-admin token on the machine
to fetch a new registration each time. That token is the one secret the machine must not
hold. `job-completed.sh` instead removes every container, volume, image, the build cache
and the job's workspace after each job. That is tidying, not isolation.

One job at a time: the services bind the host ports 5432 and 3306.
