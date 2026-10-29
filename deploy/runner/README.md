# Self-hosted runner for the database jobs

The three hub jobs that run the whole suite against a database (`hub-sqlite`,
`hub-postgresql`, `hub-mariadb` in `.github/workflows/ci.yml`) may run on a machine
of the maintainer's instead of a GitHub-hosted runner. Everything else stays hosted.

## Which runner a job gets

`ci.yml` reads the repository variable `HUB_RUNNER_LABEL` (Settings → Secrets and variables →
Actions → Variables): a label prefix, for example `maity-hub`. Each database job then asks for one
runner of its own type: `hub-sqlite` for `[self-hosted, maity-hub-sqlite]`, `hub-postgresql` for
`maity-hub-pg`, `hub-mariadb` for `maity-hub-maria`.

- **One runner service per job type**, so the three jobs of a pull request run side by side, and two
  pull requests queue only per type. A pool of identical runners would let two Postgres jobs run at
  once, both binding the host port 5432 for their service container (`ports: 127.0.0.1:5432`).
- Each service sets `PYTEST_ARGS=-n 2` in its unit: two workers per job, six on the machine's
  eight cores. Hosted runners keep `-n auto`.
- Variable unset or empty: GitHub-hosted (`ubuntu-latest`). **Deleting the variable is the whole
  fallback**, no commit needed. Runs already queued for a self-hosted label keep it, so cancel and
  rerun them after deleting the variable.
- Set: pushes to `main` and pull requests from this repository use the runners; the condition sends
  pull requests from forks to the hosted runners.

## The trust boundary, stated honestly

**The condition in `ci.yml` is not a protection against a fork.** A pull request from a
fork runs the `ci.yml` of the fork's merge commit; the fork can write
`runs-on: [self-hosted, maity-hub-pg]` itself. What keeps a fork's code off the machine is
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

## What went wrong the first time, and the limits

The first run of the three services (`-n 3` each, no limits, all three started at once) took the machine down two and a half minutes after the
three database jobs of one pull request started: the VirtualBox guest on the maintainer's workstation stopped, the
runners vanished mid-job (the jobs ended as "failure" with `make check` unfinished), and the machine was back after
a reboot with CI runs still queued on the labels. Memory was not the cause (one job peaked at 5.2 GB of 19.9 GB); nine
workers, three Docker stacks and three installs on eight vCPUs, nothing else left for the host, are the suspect.
So the machine is capped, not trusted:

- `maity-runner@.service`: `Slice=user-<uid>.slice` (into the capped tree of the runner user), `CPUQuota=150%`, `Nice=10`, `CPUWeight=20`, `IOWeight=20`, `MemoryMax=4G`, no swap,
  and `PYTEST_ARGS=-n 2`.
- `user-slice-limits.conf`: one cap for everything the runner user runs, the rootless Docker and its database
  containers included (the unit's own cap does not reach them, they run under the user's dockerd): at most 4 of 8 cores,
  low CPU and I/O weight, 8 GB, no swap. `install-services.sh` installs it as a drop-in of `user-<uid>.slice`, and the units sit in that slice (`Slice=`), so the
  caps add up to the one: check with `systemctl show -p ControlGroup maity-runner@pg` (it must end up under `user-<uid>.slice`).
- **Start with one service.** `install-services.sh` installs `INSTANCES=pg` by default; start it with the maintainer at
  the machine and `vmstat 5` running. `sqlite` and `maria` are added one at a time (`INSTANCES=sqlite install-services.sh`,
  then `install-python.sh`, then `systemctl enable --now`), each only after the previous one ran jobs without a stall. If CI runs are queued on a label whose service is
  stopped, cancel and rerun them (deleting `HUB_RUNNER_LABEL` does not re-route runs that are already queued).

## What the machine must be

- A user of its own with no `sudo`, no group of the people who work on the machine, and no
  read access to their homes (`sudo -u <runner-user> ls /home/<other>` must fail). No
  deploy keys, kubeconfig or tokens of the project anywhere that user can read.
- The runner lives outside the runner user's home and is owned by root:
  `/opt/actions-runner-<type>` (with `run.sh`, `bin/`, the registration files `.runner` and
  `.credentials*`; one directory per runner instance), the hook in `/opt/maity-runner-hooks/` (not inside the runner's own
  directory, which GitHub's documentation advises against), and the unit in
  `/etc/systemd/system/`. The runner user owns only `/opt/actions-runner-<type>/_work`, `_diag` and
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
  read the environment of later jobs, and of the jobs running at the same time on the other
  runner instances (`/proc/<pid>/environ` with their `GITHUB_TOKEN`, their `_work` and `_tool` under
  `/opt/actions-runner-<other>`: the three services share one uid and one Docker). That is one more reason for "reinstall after a malicious
  job", and lingering is there only for the rootless Docker.
- The tool cache (Python from `setup-python`) is kept between jobs and is writable for the
  runner user: a job can replace it for the later ones. That is part of the boundary above.

## Install

0. **Coming from the single runner of the first version?** First stop it, because the scripts below refuse while
   any runner of the runner user runs: remove the runner in GitHub (Settings → Actions → Runners),
   `systemctl disable --now maity-runner`, delete `/etc/systemd/system/maity-runner.service` and
   `/opt/actions-runner`, and the repository variable `HUB_RUNNER` (no longer read). Containers a cut-off job left running
   (`docker ps` as the runner user) hold the ports 5432 and 3306 for good once the runner is gone: remove them. A fresh install has nothing to do here.
1. Create the user (`<runner-user>`, uid `<uid>`), enable lingering, install rootless Docker
   for it (see above). On a fresh rented server `bootstrap-server.sh` does this step and the firewall rules;
   [SERVER-SETUP.md](SERVER-SETUP.md) has the whole procedure for such servers.
2. Download the runner (Linux x64) from GitHub's "New self-hosted runner" page as a tarball and get a
   registration token from that page (Settings → Actions → Runners; valid for an hour).
3. As root, with every `maity-runner*` service stopped and no container left in the runner user's Docker (stopping a
   service ends the runner but not the service containers of a job it was running; `docker ps` as the runner user
   must be empty, the script refuses otherwise): `RUNNER_TOKEN=<token> RUNNER_TARBALL=<tarball> install-services.sh`. For each
   selected instance (default `pg` only; `INSTANCES="sqlite maria"` adds others later) it unpacks the runner to `/opt/actions-runner-<type>`, runs `config.sh` **as the
   runner user** (as root it refuses: "Must not run with sudo"; with `--disableupdate`, because the runner's
   self-update would write into its own directory, which the runner user may not: update by hand, as root, when
   GitHub asks for a newer version), registers it as `maity-vm-<type>` with the label `maity-hub-<type>`, hands the
   files to root, and lets the runner user read only its registration (`chgrp <runner-user>` and `chmod 640` on
   `.runner`, `.credentials`, `.credentials_rsaparams`: a root-owned 0600 `.credentials_rsaparams` stops the
   runner from starting; the `chgrp` assumes a group named like the user, the default on Debian and Ubuntu).
   `_work`, `_diag` and `_temp` belong to the runner user. It also installs `job-completed.sh` into
   `/opt/maity-runner-hooks/` (root-owned) and the template unit `maity-runner@.service`.
   The units start `bin/runsvc.sh`, not `run.sh` (which writes into the runner's directory), and use
   `KillMode=control-group`. The hook's output is shown in the job log (step "Complete runner"), which anyone
   can read in a public repository.
4. For each instance, as root, with no job running (it restarts the service if it is running and never starts one; the script refuses otherwise unless
   `FORCE=1`): `RUNNER_DIR=/opt/actions-runner-<type> SERVICE=maity-runner@<type> install-python.sh`. The jobs use
   `actions/setup-python` for 3.12, which has no Python for Debian and would fail; the script installs 3.12 with
   uv as the runner user, puts it in the runner's tool cache where `setup-python` looks first, removes uv's PEP 668
   "externally managed" marker from that private copy (without it `pip install` fails in the jobs), and replaces
   the stored `.path`.
5. `systemctl enable --now maity-runner@pg` (the instance(s) you installed, one at a time); GitHub shows it as Idle.
6. Set the fork-approval setting above, then `HUB_RUNNER_LABEL` to `maity-hub`.

## Why not an ephemeral runner

An ephemeral runner registers per job, which needs a repository-admin token on the machine
to fetch a new registration each time. That token is the one secret the machine must not
hold. `job-completed.sh` instead removes every container, volume, image, the build cache
and the job's workspace after each job. That is tidying, not isolation.

One job at a time per runner, and one runner per job type: the services bind the host ports 5432 (Postgres) and
3306 (MariaDB).
