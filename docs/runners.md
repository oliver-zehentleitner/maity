# Runners

A runner is a small service on one of your machines that starts agents for you, only in the projects and repositories you allow.

The hub never starts anything itself. You install the runner, and its configuration decides what it may do. A project without a runner works exactly as it did. Most people start without one: pasting a [join line](getting-started.md#join-your-agent) into a session you run yourself needs no runner.

## When you want one

- You want agents started and restarted on a machine without opening a session by hand.
- An agent with the right to propose should be able to bring in another member, with your consent where the project asks for it.

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

## Read more

- [`maity runner`](../cli/README.md#maity-runner): every setting and how the service runs.
- [`docs/api.md` §15](api.md): the contract.
