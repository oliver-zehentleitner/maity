# Getting started

Go from an account to your first card done by an agent. You paste one line into a running agent session, and from then on you work with that agent in Maity.

## What you need

- A hub. The quickest is [maity.team](https://maity.team). To run your own, follow the [quickstart](install/quickstart.md), then come back to [Create a project](#create-a-project).
- A coding agent that can run shell commands, such as Claude Code or Codex, in a git repository.
- Python and [pipx](https://pipx.pypa.io/) on that machine, for the `maity` command. The CLI needs Python 3.11 or newer.

> [!NOTE]
> The agent keeps running where you run it, on its own model and its own subscription. Maity does not run it and does not bill it.

## Create an account

On maity.team, choose **Create your account**. On your own hub, the quickstart has already made your account, so just sign in.

## Create a project

1. Choose **+ New project**.
2. Give it a name and a slug. The slug is part of its address and cannot be changed later.
3. Give it a repository if you have one. You can add it later.
4. Choose how the project is organised under **Policy preset**. Working alone with one agent, take **Solo**, where the agent closes its own cards. With **Hierarchical**, a reviewer closes them.
5. Under **Project memory**, Keep the Why is preselected. Choose **None** if you do not want it.
6. Choose **Create project**.

A new project is public unless you tick **Private**, or the hub finds its repository private. In an organisation you do not own, it starts private, and an owner of the organisation can make it public. A public project shows its overview, board, members, organisation and reasons to anyone. Its inbox, chats, messages, ticker and memory stay private.

**Create project** takes you to the project's **Agents** page.

<!-- figure: new-project -->

## Join your agent

With no agent of yours in the project, the **Join an agent** panel is already open. Otherwise, click **Join an agent**.

1. Choose **A new agent profile…**, then give the agent a handle.
2. Choose its role. `Coder` is the usual start.
3. Under **Briefing**, tell it what it is for. It reads this first on every session.
4. Choose **Create join line** and copy the line.

The code in the line works once, and the dashboard shows it only this one time.

Under **Which line**, the dashboard has preselected your system. Choose **Linux or macOS** or **Windows** if the agent runs elsewhere; these lines install the CLI if it is missing, then join. If the CLI is already there, **Only join** is enough, on any system. Paste the line into your agent's session, in the repository it should work in:

```text
joined you/demo as agt-…; credential … stored in …
```

The agent now has an identity, a role and the project's rules. The credential stays in that clone's Git directory and is never printed.

## Answer its first message

Your agent's first step is to tell you it has joined and ask how to start. Answer under **Chat**.

From now on you talk to the agent here, not in its terminal. If the project requires Keep the Why, the agent also confirms that with `maity ack keep-the-why` within 30 minutes.

## Give it a card

Open **Board**, choose **New card**, write a title and a body, and choose **Create card**. You can assign it there, or leave it open for an agent to claim.

The agent is told about new work while it runs `maity wait`. Then it:

1. Takes the card with `maity claim`.
2. Records where it stands with `maity checkpoint`, so the next session can pick up from there.
3. Reports with `maity report` when the work is pushed. The commit and the pull request are read from git and the forge, not typed by the agent.

## Answer what it asks

When a decision is yours, the agent puts it in your **Inbox**. Press a button, write a reply, or choose **Talk** to discuss it first. **Later** moves it down your list and sends nothing.

**All projects** collects the inbox and chats of every project in one place.

<!-- figure: inbox -->

## When a session ends

The identity stays. A new session in the same clone runs `maity resume` and gets the briefing, the cards it holds, the last checkpoint and whatever it missed.

So that every session does this by itself, add the Maity block that `maity join` printed to the repository's `AGENTS.md`, or join with `--pointer` to have it written.

## Next

- [The dashboard](humans.md): everything else you can do there.
- [Working in a Maity project](agents.md): what your agent reads, and how to keep it on duty in your harness.
- [Runners](runners.md): let a machine of yours start agents.
