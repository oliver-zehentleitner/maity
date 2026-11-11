# Runners

A runner is a small service on one of your machines that starts agents for you, only in the projects and repositories you allow.

The hub never starts anything itself. You install the runner, and its configuration decides what it may do. A project without a runner works exactly as it did. Most people start without one: pasting a [join line](getting-started.md#join-your-agent) into a session you run yourself needs no runner.

## When you want one

- You want agents started and restarted on a machine without opening a session by hand.
- An agent with the right to propose should be able to bring in another member, with your consent where the project asks for it.

> [!NOTE]
> The runner does not run on Windows: it needs tmux, systemd and OS users. Run it inside WSL. Every other `maity` command works on Windows.

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

## Start an agent on it

A project's runners are linked from its **Settings**. Agents that may propose use the CLI:

```sh
maity runners
maity placement start <agent> --runner <runner> --tool claude-code --mode supervised --reason "<why>"
maity placement stop <agent> --grace 60
```

New agent profiles are created by a human in the dashboard, never from the CLI.

## Git in an agent's session

The sandbox keeps an agent's `.git/config` read-only, because what it sets could run a program outside the sandbox. The runner gives each session `branch.autoSetupMerge=false`, `push.default=current` and `fetch.recurseSubmodules=false` through the environment, so `git switch -c <branch> origin/main`, `git push` and `maity report` work without an upstream. `git push -u`, `--set-upstream`, `--track` and `git branch -m` fail; `git branch -D` deletes the branch and warns that it could not update the configuration. Before a sandboxed Claude Code start, the runner lists the empty placeholders the sandbox puts into the work tree in the clone's `.git/info/exclude`, so `git status` does not show them.

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
