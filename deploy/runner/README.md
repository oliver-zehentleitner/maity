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
- A pull request from a fork always runs hosted, whatever the variable says: a fork's code
  never reaches the machine.
- Pushes to `main` and pull requests from this repository use the runner.

## What the machine must be

- A user of its own with no `sudo`, no group of the people who work on the machine, and no
  read access to their homes (`sudo -u <runner-user> ls /home/<other>` must fail). No
  deploy keys, kubeconfig or tokens of the project anywhere that user can read.
- Rootless Docker for that user (`dockerd-rootless-setuptool.sh install`): the jobs'
  `services:` (PostgreSQL, MariaDB) need a Docker API, and the Docker group would be root.
- Settings → Actions → General → "Fork pull request workflows": require approval for all
  outside collaborators.

## Install

1. Create the user, enable lingering, install rootless Docker (see above).
2. On GitHub: Settings → Actions → Runners → New self-hosted runner (Linux x64). As the
   runner user, unpack it to `~/actions-runner`, run `config.sh --url <repo> --labels
   maity-hub --unattended` with the registration token from that page.
3. Copy `job-completed.sh` and `maity-runner.service` from here to `~/actions-runner/` and
   `~/.config/systemd/user/`, then `systemctl --user enable --now maity-runner`.
4. Set `HUB_RUNNER` to `["self-hosted","maity-hub"]`.

## Why not an ephemeral runner

An ephemeral runner registers per job, which needs a repository-admin token on the
machine to fetch a new registration each time. That token is the one secret the machine
must not hold. `job-completed.sh` instead removes every container, network, volume and the
job's workspace after each job; only code of this repository runs there.

One job at a time: the services bind the host ports 5432 and 3306.
