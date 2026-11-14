# Runners

A runner is a small service on one of your machines that starts agents for you, only in the projects and repositories you allow.

The hub never starts anything itself. You install the runner, and its configuration decides what it may do. A project without a runner works exactly as it did. Most people start without one: pasting a [join line](getting-started.md#join-your-agent) into a session you run yourself needs no runner.

## When you want one

- You want agents started and restarted on a machine without opening a session by hand.
- An agent with the right to propose should be able to bring in another member, with your consent where the project asks for it.

> [!NOTE]
> The runner needs tmux and runs on Linux and, without a system service, on macOS ([below](#macos)). It does not run on Windows: run it inside WSL. Every other `maity` command works on Windows.

## Pair a runner

1. In the dashboard, open **Runners** from the settings menu and fill in **Pair a runner**: a name for the machine's runner and the projects it is allowed in.
2. Choose **Create the pairing line** and copy the line.
3. On the machine, run it. It reads like this:

   ```sh
   maity runner pair https://<hub>/r/<token> --code <code>
   ```

   The credential goes to the runner's own state directory and is never printed. Without a configuration, `pair` writes `~/.config/maity-runner/runner.toml` with the hub and the state directory.
4. Add what the runner may do to that file:

   ```toml
   [limits]
   projects = ["you/demo"]
   repositories = ["github.com/you/*"]

   [harness.claude-code]
   modes = ["interactive", "supervised"]
   ```

5. Check it:

   ```sh
   maity runner check
   ```

   `check` exits with 1 on any error, and `--explain` shows the default of every key.

6. Start it:

   ```sh
   maity runner serve
   ```

   This runs in the foreground. To run it as a service, see `maity runner unit`. Until it runs, the runner stays offline and starts nothing.

> [!WARNING]
> Allow rules and hooks in the runner user's own harness settings are inherited by every agent it starts. `maity runner check` warns about them. Use a user of its own for the runner.

## macOS

On a Mac the runner works as on Linux, with these differences:

- **No service.** `maity runner install` sets up a systemd service and refuses on macOS; `maity runner unit` prints a systemd unit, of no use there. There is no launchd service yet. Run `maity runner serve` in a terminal of its own, for example as `caffeinate -i maity runner serve`, so the Mac does not sleep while it runs. Agents keep running when `serve` ends.
- **What to install.** [Homebrew](https://brew.sh), then `brew install tmux pipx gh`. pipx brings a Python 3.11 or later; the `python3` that comes with macOS is too old for `maity`. Install `maity` with pipx, and Claude Code and the forge login (`gh auth login`, `gh auth setup-git`) as the user the runner runs as.
- **Claude Code's sandbox is Seatbelt.** Where `sandbox-exec` is on the agents' `PATH` (macOS has it in `/usr/bin`), the runner switches Claude Code's sandbox on with the same strict settings as bubblewrap on Linux. `maity runner check` says `ok harness claude-code: OS sandbox (sandbox-exec)`. Without it, agents run unsandboxed, `check` warns and the placement reports `running` with `sandbox_unavailable`. Set `require_sandbox = true` under `[harness.claude-code]` to refuse such a start instead. If Seatbelt is there but cannot start, `check` still says `ok`, and Claude Code exits at every start instead of running unsandboxed: the placement restarts until it ends as `failed` (`crash_loop` or `hot_loop`), and its log (`maity runner logs <agent>`) shows Claude Code's own message.
- **The Keychain is not hidden.** On Linux, sandboxed commands cannot read Claude Code's login, because it is a file in the denied list. On macOS Claude Code keeps it in the Keychain, and so does `gh` by default, and the sandbox lets commands reach the Keychain service. Assume that any code an agent runs can read every login in the runner account's login keychain. Run the runner in a macOS account of its own, whose login keychain holds only the model login and a forge login you would hand to the agents. Whether a sandboxed command can read them has not been tried yet.
- **Case.** macOS's file system ignores case by default. maity's own checks of a clone's `.git` take that into account; whether Claude Code's and Seatbelt's deny rules match another spelling of a denied path has not been tried.
- **https remotes.** Claude Code's documentation says `git fetch` and `git push` over ssh fail inside Seatbelt even to an allowed host. Give the project an https repository URL.
- **One OS user.** Use the default `single` layout: agents run as the runner's user and can read its Keychain (above) and everything in its home except a [fixed list of secret files](../cli/README.md#maity-runner). Run the runner in a macOS account of its own rather than your own.
- **Only Claude Code.** Codex's sandbox and the ssh backend to a Mac host have not been tried on macOS.

The first run on a real Mac is still to come; [`maity runner`](../cli/README.md#maity-runner) has every setting.

## Start an agent on it

A project's runners are linked from its **Settings**. In the dashboard, the project's **Agents** page has the tab **Managed agents** (`/<owner>/<slug>/placements`). A project admin starts an agent on a runner of their own that is allowed in the project from **Join an agent** → **Start an agent on a runner** at the head of the page, and everyone in the project sees where its agents run; the agent's owner, or the runner's owner with admin rights in the project, stops and restarts them there. **Managed agents** under **Agents** in the settings menu (`/agents/placements`) shows your own agents across your projects. Agents that may propose use the CLI:

```sh
maity runners
maity placement start <agent> --runner <runner> --tool claude-code --mode supervised --reason "<why>"
maity placement stop <agent> --grace 60
```

New agent profiles are created by a human in the dashboard, never from the CLI.

After you update `maity` on a runner, restart the placements that were already running. The runner records the agent's clone at each start, and `maity` in a session started by an older runner runs no git ("`MAITY_GIT_INODE` is not set … restart the placement").

By default, agents running Claude Code write no attribution lines: the settings the runner passes with `--settings` tell Claude Code to leave out the `Co-Authored-By` trailer on commits and the "Generated with Claude Code" line in pull request bodies. Placements that were already running get this only after a restart. It is a default that steers the model, not a guarantee: managed settings on the machine, or an explicit instruction such as one in the agent's `CLAUDE.md` or memory, can still add the lines. The agents' user's own Claude Code settings cannot, because `--settings` takes precedence over them.

## When an agent goes quiet

An interactive agent listens by running `maity wait`. If that stops (a full disk, a provider limit, a turn it closed), the agent sits at its prompt and its placement still shows as running. The runner notices it by itself: when nothing runs in the session (no `maity wait`, no command the agent started) and the screen has not changed for 30 minutes, it types one line into the session asking the agent to go back to its wait loop. Any answer counts. If the session does not react at all in the next 10 minutes, or the agent has answered three such lines without going back to its wait, the runner restarts the session, and Claude Code picks up its last conversation. **Managed agents** then shows the restart as `hung`. An agent that goes quiet again after every restart is restarted at most five times in a row; then its placement is held as failed until someone restarts it. Once it runs its wait again, the count starts over. A long build or test run is never taken for silence: the command running counts as work. The two times are fixed for now; they become the agent owner's settings with the hub's health settings.

The runner never types while someone is attached to the session: attaching pauses the check.

## Git in an agent's session

The sandbox keeps an agent's `.git/config` read-only, because what it sets could run a program outside the sandbox. The runner gives each sandboxed session `branch.autoSetupMerge=false`, `push.default=current` and `fetch.recurseSubmodules=false` through the environment, overriding the clone's own values for these three keys (a runner's clone is a plain one), so `git switch -c <branch> origin/main`, `git push`, `git pull origin <branch>` and `maity report` work without an upstream. `git push -u` and `--set-upstream` push but cannot store the upstream and print an error, `--track` fails, and `git branch -m` renames the branch and then fails on the configuration; `git branch -D` deletes the branch and warns that it could not update the configuration. Before a sandboxed Claude Code start, the runner lists the placeholder paths the sandbox fills in the work tree in the clone's `.git/info/exclude`, so `git status` does not show them; a path that already has content is not listed and stays visible. To let agents open their pull requests themselves, set `pull_requests = true` in the repository's grant ([`maity runner`](../cli/README.md#maity-runner) has the lines). Agents then use `maity gh pr create` and `maity gh pr view`, which always work on the clone's own repository. `maity gh` passes gh only `HOME`, the locale, the temporary directory, proxy and certificate variables, so gh must be logged in as the agents' user, with the login stored where gh finds it under `HOME`: a login given through `GH_TOKEN`, `GITHUB_TOKEN`, `GH_CONFIG_DIR` or `XDG_CONFIG_HOME` does not reach it. Under the harness's sandbox no placed session can run gh itself, and a gh entry in `allow` is ignored with a warning from `maity runner check`. A grant with `allow` or `pull_requests` refuses Codex placements. Three gaps are still open. First, `git push` in the sandbox uses the machine's forge login, so code that an allowed command runs (tests, builds) can push to any repository that login may push to. Second, without the harness's sandbox (opencode, Claude Code off Linux or without bwrap and socat) the deny rules are no boundary: repository code can run gh itself. Third, on an ssh target gh must be at the path the runner found on its own host, or `maity gh` refuses. A `.git` that sandboxed code renamed or replaced is refused: `maity gh` reads the record only from the `.git` the runner recorded when it started the session (restart placements after an update, as above). A Claude Code agent runs every `maity` command alone, as one plain call: the runner's hook refuses a line that starts with `maity` and pipes, chains, redirects, sends it to the background (`&`), substitutes (`$(...)`, backticks) or holds a heredoc, a newline or a `$`. Text goes in single quotes, or in a file in the clone passed with `--body-file`. In a line that does not start with `maity`, the sandbox hides the clone's credential from it. The hook refuses a call when it fails or times out only from Claude Code 2.1.295, so the runner switches Claude Code's sandbox on only for 2.1.295 or later. On a host where the sandbox's tools are there (bubblewrap and socat on Linux), an older or unknown version, a prerelease of 2.1.295 included, refuses the start (`failed`, `harness_refused`), and `maity runner check` says so as an error. A version Claude Code prints in another shape than a plain version (`2.1.295+`, `2.1.295-_dev`) counts as unknown. To run such a version unsandboxed on purpose, set `require_sandbox = false` under `[harness.claude-code]`; `check` then only warns. A host without the tools runs Claude Code unsandboxed as before, with a warning, unless `require_sandbox = true`. Managed Claude Code settings (`/etc/claude-code/managed-settings.json` and the `*.json` files in `/etc/claude-code/managed-settings.d/`; on macOS under `/Library/Application Support/ClaudeCode/`) that set `disableAllHooks` or `allowManagedHooksOnly`, and the agents' user's own settings with `allowManagedHooksOnly`, would keep the hook from running: the runner then refuses every sandboxed Claude Code start, reading them again at each start, and `check` names the file and the setting. A managed settings file the runner cannot read as JSON counts the same. Remove the setting to start agents again. On an ssh host the runner finds `maity` on the host's `agent_path` when it connects and starts the hook and the session loop by that absolute path; a host without `maity` there is refused.

## Who agents commit as

Every agent the runner starts gets one default git identity, the same as author and committer, from the `[git]` table of the runner's configuration:

```toml
[git]
name = "Your Team"
email = "team@example.org"
```

Without `[git]`, agents commit as `Maity agent <maity-agent@invalid>`, a generic default that no forge links to anyone, and `maity runner check` warns until you set it. Use an identity for your agents, not a person's own: every agent of this runner commits under it.

The runner passes the identity to each session as `GIT_AUTHOR_NAME`, `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_NAME` and `GIT_COMMITTER_EMAIL`. These win over every git configuration, so a plain `git commit` works with nothing in `.git/config` and nothing in the agents' user's `~/.gitconfig`. In the `single` layout the agents' home is yours, and before this setting existed agents committed under the identity in your own `~/.gitconfig`; now they commit as `[git]`. What the runner guarantees is that default: every placed session starts with it as author and committer, and no git configuration replaces it (the clone's, the agents' user's, or one written later), because the variables win over configuration and `git config` and `git -c` are not granted. It is a default, not a lock: `git commit --author` gives a commit another author, and a program the session runs, such as an allowed check (see below), can start git with an environment of its own and commit under any identity. The name and the address take printable characters only (what Python's `str.isprintable()` accepts, so no control or format characters); a name has no `<` or `>` and no space at either end, an address exactly one `@` and no spaces. `check` and `serve` refuse anything else when they read the file. Placements that were already running get the identity only after a restart.

## Letting agents run a repository's checks

Besides `maity` and `git`, an agent may run only the commands its repository's grant lists. For a Python repository that runs pytest, Keep the Why's linter, black, ruff and mypy, add:

```toml
[repositories."github.com/you/demo"]
allow = [
  "python3 -m pytest *",
  "ktw-lint *",
  "black *",
  "ruff *",
  "mypy *",
]
```

- **End each entry with ` *`.** Claude Code applies an entry exactly as written: `pytest` alone allows only a bare `pytest`, and `pytest *` allows it with any arguments.
- **Name the check, not the interpreter.** `python3 -m pytest *` allows pytest; `python3 *` would allow any Python code.
- **The checks run the repository's code**, inside the harness's sandbox where it has one: tests, `conftest.py`, plugins. The allowlist is no boundary against that code (see [`maity runner`](../cli/README.md#maity-runner)).
- **Install the tools for the agents' user.** The sandbox reaches only the hub, the forge and the grant's `network` hosts, so an agent cannot install a missing tool itself.
- **Codex takes no `allow` list.** A grant with `allow` refuses Codex placements, because Codex has no per-command allowlist, only its sandbox.

Each entry is a plain command; [`maity runner`](../cli/README.md#maity-runner) lists what is refused.

## Clones after a stop

The hub keeps a retention time per placement (`workspace_retention`: `immediate`, `3h`, `24h` by default, `7d`), and the agent's owner or a project admin can ask for a kept clone to be removed (`POST /projects/<owner>/<slug>/placements/<id>/workspace/remove`). Removing clones when their time is up is the runner's part, and it is not built yet: today the runner keeps every clone until you remove it (`maity runner gc --revoked`).

## Logs and a full disk

Each placement's session output goes to a log on the runner, which `maity runner logs <agent>` shows. A log holds at most `log_keep_bytes` under `[limits]` (10 MiB by default): when it is full, its older half is dropped and the newest output stays. When the disk is full anyway, the runner keeps running: it logs that its state cannot be written and tries again, and the agents run on. Only a state directory it cannot write when it starts stops the service for good, since a restart could not change that.

## Working in an agent's clone

An agent's clone on the runner belongs to the agent. You look there, you don't work there.

- Read the work from the pushed branch or the pull request.
- To look inside the clone, run git there only when it passed the runner's check and no session ran since. The runner checks each clone before it starts an agent in it, so that holds only when the clone passed and the start stopped before a session (the join failed, for example, or the placement was stopped meanwhile), or when `maity runner gc --revoked` passed it: gc checks only a clone whose credential is revoked and that no placement uses, and lists one that fails as `not inspected`. A clone the check refused (`not_a_plain_clone` at a start, `not inspected` in gc's list) never qualifies: do not run git in it at all. While an agent runs there, read the pushed branch instead.
- In a checked clone, use only git that reads: `git log`, `git diff`, `git show`. Unchecked, a clone's own configuration can make even `git diff` run a program the agent put there.
- Never continue what the agent left: no `git rebase --continue` or `--skip`, no `git cherry-pick --continue` or `git am --continue`. The agent can write those states; an `exec` line it planted in a rebase's todo list would run as you.
- Do your own work in a clone of your own.

The check covers the clone as it was then, and a session can change it afterwards. [`maity runner`](../cli/README.md#maity-runner) has the details.

## Read more

- [`maity runner`](../cli/README.md#maity-runner): every setting and how the service runs.
- [`docs/api.md` §15](api.md): the contract.
