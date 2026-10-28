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
- The runner's files (`~/actions-runner` with `run.sh`, the hook, the registration files
  `.runner` and `.credentials*`, and the user unit) are owned by another user and only
  readable for the runner user; the runner user owns just `_work`, `_diag`, `_temp` and its
  Docker data. A job that can rewrite the hook or `run.sh` takes over every later job.
- Rootless Docker for that user (`dockerd-rootless-setuptool.sh install`): the jobs'
  `services:` (PostgreSQL, MariaDB) need a Docker API, and the Docker group would be root.
  The services bind to `127.0.0.1` only, with their images pinned by digest in `ci.yml`.
- A firewall rule per user that keeps the runner user away from local services and the
  internal network, for example `iptables -A OUTPUT -m owner --uid-owner <runner-user>
  -d 127.0.0.0/8,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16 -j REJECT` (with the loopback
  ports of its own Docker services allowed first).
- The tool cache (Python from `setup-python`) is kept between jobs and is writable for the
  runner user: a job can replace it for the later ones. That is part of the boundary above.

## Install

1. Create the user, enable lingering, install rootless Docker (see above).
2. On GitHub: Settings → Actions → Runners → New self-hosted runner (Linux x64). Unpack it
   to `~/actions-runner` and run `config.sh --url <repo> --labels maity-hub --unattended`
   with the registration token from that page, then hand the files over as described above.
3. Copy `job-completed.sh` and `maity-runner.service` from here to `~/actions-runner/` and
   `~/.config/systemd/user/`, then `systemctl --user enable --now maity-runner`. The unit
   uses `KillMode=control-group`, so a restart also ends processes a job left behind.
4. Set `HUB_RUNNER` to `["self-hosted","maity-hub"]`, and the fork-approval setting above.

## Why not an ephemeral runner

An ephemeral runner registers per job, which needs a repository-admin token on the machine
to fetch a new registration each time. That token is the one secret the machine must not
hold. `job-completed.sh` instead removes every container, volume, image, the build cache
and the job's workspace after each job. That is tidying, not isolation.

One job at a time: the services bind the host ports 5432 and 3306.
