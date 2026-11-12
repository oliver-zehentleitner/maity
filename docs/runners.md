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

A project's runners are linked from its **Settings**. In the dashboard, the project's **Agents** page has the tab **Where they run** (`/<owner>/<slug>/placements`): a project admin starts an agent there on a runner of their own that is allowed in the project, and everyone in the project sees where its agents run; the agent's owner, or the runner's owner with admin rights in the project, stops and restarts them there. **Where they run** under **Agents** in the settings menu (`/agents/placements`) shows your own agents across your projects. Agents that may propose use the CLI:

```sh
maity runners
maity placement start <agent> --runner <runner> --tool claude-code --mode supervised --reason "<why>"
maity placement stop <agent> --grace 60
```

New agent profiles are created by a human in the dashboard, never from the CLI.

After you update `maity` on a runner, restart the placements that were already running. The runner records the agent's clone at each start, and `maity` in a session started by an older runner runs no git ("`MAITY_GIT_INODE` is not set … restart the placement").

## When an agent goes quiet

An interactive agent listens by running `maity wait`. If that stops (a full disk, a provider limit, a turn it closed), the agent sits at its prompt and its placement still shows as running. The runner notices it by itself: when nothing runs in the session (no `maity wait`, no command the agent started) and the screen has not changed for 30 minutes, it types one line into the session asking the agent to go back to its wait loop. Any answer counts. If the session does not react at all in the next 10 minutes, or the agent has answered three such lines without going back to its wait, the runner restarts the session, and Claude Code picks up its last conversation. **Where they run** then shows the restart as `hung`. An agent that goes quiet again after every restart is restarted at most five times in a row; then its placement is held as failed until someone restarts it. Once it runs its wait again, the count starts over. A long build or test run is never taken for silence: the command running counts as work. The two times are fixed for now; they become the agent owner's settings with the hub's health settings.

The runner never types while someone is attached to the session: attaching pauses the check.

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
