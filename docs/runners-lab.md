# The runner lab: what is tested where

This page tracks where the runner and its harnesses are tested, how the test machines are set up, and which gaps are still open. It is the team's current state, not a promise. [Runners](runners.md) explains how a runner works; this page says how well it works where.

**A pull request that changes the runner updates this page in the same pull request.**

Status as of **2026-11-18**, maity **0.1.0a15**. Environments are named by OS and version only.

## Tested environments

| Environment | Layout | Notes |
|---|---|---|
| **Debian 13** | `single`, systemd service | Unprivileged user namespaces allowed; no AppArmor userns restriction. |
| **Ubuntu 26.04** | `single`, systemd service | Ships AppArmor's `bwrap-userns-restrict`; needs the host fix in [Ubuntu: nested user namespaces](runners.md#ubuntu-nested-user-namespaces) for Claude Code's sandbox. |
| macOS | – | Not run yet ([Runners: macOS](runners.md#macos)). |
| Windows | – | Not run yet. |

## Status matrix

✓ seen working · ✗ seen failing · – not tested yet · n/a does not apply. The card says why.

### Ubuntu 26.04 (with the AppArmor host fix)

| Harness, mode | Start | `resume` / `wait` | Commands and tests | Subagent with Bash | PR via `maity gh` | Restart, session taken over | Stop | Sandbox |
|---|---|---|---|---|---|---|---|---|
| claude-code, interactive | ✓ | ✓ | ✓ main session | ✗ permission layer (tsk-66zyvc4xnhtv, #1962) | ✓ `pr view` | ✓ | – | on (bubblewrap) |
| codex, interactive | ✓ session | ✗ | ✗ every exec denied (tsk-hv7jbgy75zjt) | n/a | n/a: not granted to codex | ✓ | ✓ | on, but blocks itself |
| antigravity, supervised | ✓ | ✓ | ✓, unsandboxed | n/a | – | ✓ | – | off (`sandbox_unavailable`) |
| opencode | – | – | – | n/a | – | – | – | none |

Without the host fix, every sandboxed Claude Code command fails on the seccomp step (tsk-5b5x3k5zvg7x). `maity runner check` reports that as an error.

### Debian 13

| Harness, mode | Start | `resume` / `wait` | Commands and tests | Subagent with Bash | PR via `maity gh` | Restart, session taken over | Stop | Sandbox |
|---|---|---|---|---|---|---|---|---|
| claude-code, interactive | ✓ | ✓ | ✓ | – | – | – | – | on (bubblewrap); the nested namespace starts |
| codex, interactive | – | – | – | n/a | n/a: not granted to codex | – | – | on |
| antigravity, supervised | ✓ | – | – | n/a | – | – | – | off; its namespaces start |
| opencode | – | – | – | n/a | – | – | – | none |

The Debian cells not marked are still to be filled from the lab's notes.

The test cycle after each CLI release: start · `maity resume` · `maity wait` · a subagent with Bash · read and open a PR with `maity gh` · stop · a runner restart that takes the session over · `maity runner check` without false greens. Results go on the lab card (tsk-gw1e87ev707f) and into this page.

## Install the harnesses

Everything runs as the agents' user (in the `single` layout, the runner's own user, here `maity-runner`). The service's `PATH` is systemd's default, so tools in `~/.local/bin` need `agent_path` (below).

- **maity:** `pipx install maity`. Upgrade with `pipx upgrade maity`, then restart the service.
- **Claude Code and Codex:** let the runner manage them: `install = true` and `update = "daily"` under `[harness.claude-code]` and `[harness.codex]` ([Keeping Claude Code and Codex current](runners.md#keeping-claude-code-and-codex-current)). Sign in once as the agents' user: `claude` for Claude Code, and for Codex the `codex login` of the version `maity runner tools` lists.
- **Antigravity:** `agy` in `~/.local/bin` and signed in as the agents' user ([Antigravity (agy)](runners.md#antigravity-agy)).
- **OpenCode:** from the GitHub release of `sst/opencode`:
  1. Download `opencode-linux-x64.tar.gz` and `SHA256SUMS` of the release, for example with `gh release download v2.3.0 -R sst/opencode -p opencode-linux-x64.tar.gz -p SHA256SUMS`.
  2. Check it: `sha256sum -c --ignore-missing SHA256SUMS` must say `opencode-linux-x64.tar.gz: OK`.
  3. Unpack it to `~/.local/opencode/v2.3.0/opencode` and link `~/.local/bin/opencode` to it, so a later version sits beside it and the link switches.
  4. Sign in with your provider: `opencode auth login`. `opencode auth list` shows the stored provider, and `opencode models` must list the models you name in `runner.toml`.
- **gh:** `gh auth login` and `gh auth setup-git` as the agents' user, for `maity gh` and `git push`.

## Configure the runner

`~/.config/maity-runner/runner.toml`, besides the `[hub]` and state directory `pair` writes:

```toml
[limits]
projects = ["you/project"]
repositories = ["github.com/you/*"]

[git]
name = "Your agents"
email = "agents@example.org"

[backend.local]
layout = "single"
# systemd starts the service without ~/.local/bin: name it, or agy, opencode and maity are not found
agent_path = "/home/maity-runner/.local/bin:/usr/local/bin:/usr/bin:/bin"

[harness.claude-code]
modes = ["interactive", "supervised"]
install = true
update = "daily"

[harness.codex]
modes = ["interactive", "supervised"]
install = true
update = "daily"

[harness.antigravity]
modes = ["supervised", "interactive"]

[harness.opencode]
modes = ["supervised", "interactive"]
models = ["<provider>/<model>", "<provider>/<model>"]
default_model = "<provider>/<model>"

[repositories."github.com/you/project"]
allow = ["make", "make *", "python3 -m pytest *"]
network = []
pull_requests = true
```

- **`default_model`** is meant for a placement that names no model. In 0.1.0a15 it does not apply to opencode yet: such a placement runs opencode's own default model (tsk-kf2kp09d6qew). Name the model on the placement until the fix is released.
- **A repository grant** gives agents its `allow` commands and, with `pull_requests = true`, `maity gh` ([Letting agents run a repository's checks](runners.md#letting-agents-run-a-repositorys-checks)). Without a grant for a repository, its agents get neither. A Codex placement gets no pull-request grant while its sandbox is on, and `check` warns about that.
- **The service.** Either `sudo maity runner install`, or a systemd unit of your own for an existing user (`maity runner unit` prints one). After changing `runner.toml`, restart the service. Running placements are taken over (`running adopted`), not restarted.
- **Check with the service's `PATH`**, not your shell's: `env -i HOME=$HOME PATH=/usr/bin:/bin maity runner check`. Your login shell may find tools that the service does not.

### What `maity runner check` warnings mean

| Warning | Meaning |
|---|---|
| `its sandbox was checked with 2.1.x, this is 2.1.y` | Claude Code is newer than the version whose sandbox behaviour was verified. Informational. |
| `pull_requests is not given to codex` | Codex runs `maity` inside its sandbox, so it gets no `maity gh`. |
| `allow '…' is left out for antigravity` | agy does not match command grants the way Claude Code does; such commands run in agy's sandbox like any other. |
| `the namespaces agy's terminal sandbox needs do not start` | On this host agy runs commands unsandboxed. |
| `sandbox reported off … sandbox_unavailable` | agy's sandbox is reported off until the runner has seen it start, on every host for now. |
| `~/.claude/settings.json allows N rule(s) of its own` | Every Claude Code agent the runner starts inherits them; use a user of its own for the runner. |
| `could not tell whether a user namespace starts inside bubblewrap` | The nesting probe did not answer; it blames nothing. Run it by hand ([Ubuntu: nested user namespaces](runners.md#ubuntu-nested-user-namespaces)). |

## Host fixes and tradeoffs

- **Ubuntu, AppArmor:** Claude Code's sandbox needs a nested user namespace that Ubuntu's `bwrap-userns-restrict` refuses. The verified fix and its scope are in [Ubuntu: nested user namespaces](runners.md#ubuntu-nested-user-namespaces). It needs root and affects every bubblewrap sandbox on the host.
- **OpenCode has no sandbox.** Under the `single` layout an OpenCode agent can do what the agents' user can, including reading the other agents' clones. Place only test members with it until it gets one (tsk-nynpvag9zvhh).
- **Antigravity** runs unsandboxed where its namespaces do not start, and is reported `sandbox_unavailable` everywhere for now. Its command grants do not apply (above).

## Known gaps

| Gap | Where | Card |
|---|---|---|
| Codex's exec helper lives in its `CODEX_HOME`, which the runner puts inside the state directory that the sandbox profile hides, so every command is denied | Ubuntu 26.04, Codex 0.169 and 0.170 | tsk-hv7jbgy75zjt |
| Claude Code subagents get no Bash in a placement (permission layer) | both | tsk-66zyvc4xnhtv, #1962 |
| An OpenCode placement without a model runs OpenCode's own default model | both | tsk-kf2kp09d6qew |
| Coders cannot build the project's dev venv or run its full checks in a placement | both | tsk-kshmb8vc92rr |
| The clone check refuses the empty read-only `.git/config.lock` the Claude sandbox leaves behind | both | tsk-estwtzbae972, #1954 |
| A supervised agent shows as offline or away on the team page while its placement runs ("where they run" is green) | both | tsk-hv7jbgy75zjt (note nte-w7bwz93q1vnx) |
| Claude Code without its sandbox as an opt-in where the host cannot allow it | – | tsk-yp2bprwv9whv |
| `runner check` does not probe the nested user namespace on ssh hosts | ssh backend | tsk-5b5x3k5zvg7x (follow-up) |
