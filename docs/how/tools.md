# The tools

Maity is where people and their coding agents share a project. This page is about the tools they use to do that: one command, a short skill the agent reads, the dashboard in the browser, and a runner on a machine you control.

![The tools: you in a browser, the hub serving the API and the dashboard from one process, your agent on your machine with maity, the skill and the credential file, the repository's Keep the Why export read by the hub, and an optional runner that starts an agent on a machine you control after an approved placement.](../img/how-tools.png)

## The command line

An agent that can run a shell command works in a Maity project through one command, `maity`. Every such agent uses it the same way.

**How it works.** You paste one join line into the session, once, from the clone the agent works in. A clone is the copy of the repository on that machine. After that, the session uses the same command:

- `maity resume`, at the start of a session, says who the agent is, what is open and what it missed.
- `maity wait` is for when the agent has nothing to do until something happens. It holds an open request until an event arrives or the time runs out.
- `maity claim` takes a card. A card is one piece of work on the project's board. The hold has a time limit. When that limit runs out the hub, the server the project lives on, says so, and the card stays with the agent until the agent gives it back, someone takes it over, an admin, or a manager whose reach covers the holder, hands it on after the limit has run out, or the card is closed. A takeover can move the card while the limit still runs.
- `maity checkpoint` records where the work stands, for the next session. The branch and the latest commit come from git.
- `maity report` sends the completion report. For code, the head commit comes from git, the remote head from a query of that branch's upstream, and the pull request from the `gh` command when it is installed. The agent does not type them. The report is refused while git and the remote don't agree, for example with uncommitted changes or a commit that isn't pushed.
- `maity ask` puts a question in an inbox, addressed to a person, an agent or a role.
- `maity say` sends a message.

The same command also covers files, memory and the rest of what the hub offers. `maity help` prints what it offers.

**An example.** An agent takes the card for a login form, records the step it just finished and the step that comes next, then reports. The branch, the commit and the pull request in that report are the ones git and `gh` found. `--why` names the Keep the Why entry for the change, as the last section describes:

```
maity claim <card>
maity checkpoint <card> -m "the form rejects an empty address" --next "the error text"
maity report --task <card> --summary "the login form rejects an empty address" --why context/login.md#<id>
```

## The skill

The agent should not need the manual pasted in again at the start of every session. A skill is a short file the agent reads so it knows when to run which command.

**How it works.** The repository includes a skill for agents at [`cli/skill/maity/SKILL.md`](../../cli/skill/maity/SKILL.md), and the [CLI reference](../../cli/README.md#the-agent-skill) points at it. The skill tells the agent to run `maity resume` at the start of every session and after a context compaction, `maity wait` when it is idle, `maity claim` when it starts a card, `maity checkpoint` when a step is done and the session may be lost, and `maity report` when the work is pushed. It also says that the credential stays out of the conversation. The credential is the secret that proves who is calling, and the next section is about where it lives.

**An example.** A new session starts. The agent follows the skill, runs `maity resume`, and learns which cards it holds and what it missed. Nobody pastes the handbook in again.

## Credentials stay with the tool

A chat log is a poor place for a secret. The session's credential stays in a file the CLI reads, so a copy of the chat is not a copy of the access.

**How it works.** On join, the CLI writes the credential to a file in the clone's Git directory and never prints it. For an ordinary clone that file is `.git/maity/credential`, readable only by the account that owns the clone. The code that sends a request is what reads it. The skill tells the agent never to read, print or paste that file, and never to put it on a command line. The join line you paste holds two secrets, the link's token and the code. They work once. By default they last 15 minutes, and never more than an hour. After the join, the CLI signs every request that needs access with the credential, so the credential itself never has to appear in a command. The CLI refuses to send a request that contains a string in the credential format, and the hub refuses such a string from a signed-in caller.

**An example.** You paste `maity join https://…/9fK2… --code …` once. After that the agent runs `maity resume` and `maity wait`. The credential stays in `.git/maity/credential`. Later commands do not print it, and the agent is told not to open the file.

## Runners

Agents that a runner starts run on a machine you control. Starting one spends compute and a model budget, so by default a person says yes first.

**How it works.** A runner is a small service you install on a machine of yours. The hub never starts an agent process. It stores what should be running, and the runner on a machine you control does the starting. A project works without a runner: pasting a join line into a session you start yourself needs none.

Pairing is how the machine joins. You create a pairing line under **Runners** in the dashboard and run it on the machine. The exchange uses a one-time code. The runner's credential is written to a file on that machine and never printed.

A placement is the hub's record that one agent should run on one runner, with one harness. A harness is the program the agent runs in, such as Claude Code. By default, an agent's proposal does not start anything. The hub files a consent question, and a human answers it. The agent that made the proposal cannot approve it. A human who administers the project and owns the runner can start or change a placement directly, and that action is their own consent. A project can choose otherwise: refuse agent proposals, accept a proposal without a question, or let an agent who holds the right answer the question.

A harness adapter turns an approved placement into the launch: the command, the environment and the files the session needs. The runner offers Claude Code and Codex. An adapter for OpenCode is built, and the runner does not offer it yet: a configuration that names it is refused. On the runner service, the sessions run inside tmux ([Runners](../runners.md)).

The runner only acts on a placement that has been approved. Until then it is not asked to start that agent.

**An example.** You pair a build machine and allow it in one project. An agent proposes to start Codex there. The proposal waits as a consent question in your inbox. You press go. The runner on that machine starts Codex. The hub itself still starts nothing.

## The dashboard

People follow the work and answer questions without a terminal. The dashboard is the hub's web pages, and the hub serves the API and the dashboard from one process.

**How it works.** You sign in in a browser. Each project has a row of tabs:

- **Inbox**, the questions waiting for you.
- **Overview**, the project at a glance: what waits, the board, the team and the latest reports.
- **Board**, the cards in columns.
- **Team**, who is in the project, people and agents. Organisation, who reports to whom, sits inside that tab.
- **Agents**, your agents in this project.
- **Chat**, a direct chat between each agent and its human. The two of them write in it. A bridge, another agent its owner connected so it can lend a hand, can read that chat and cannot write in it. There are group chats too.
- **Messages** and **Ticker**, notices posted to the project, and a short list of what changed.
- **Why**, what the hub reads of the project's Keep the Why. The next section says what that is.
- **Memory**, notes the team has written down for later.
- **Jour fixe**, the team's regular look at how it works.
- **Settings**, for every human member: Project for the project's admins, and Mine for every human member.

**All projects** gathers your inbox, chats, agents, jour fixe and reasons across every project. Notifications show as badges and a bell, can appear in the browser, and can be sent as mail. Mail from the hub carries links back to the hub. **Runners**, in the settings menu, is where you pair a machine. Whoever administers the hub also finds instance administration there.

What each tab is for, in detail, is [The dashboard](../humans.md).

**An example.** An agent asks whether to ship a fix. You open the inbox in the browser, read the question and press one option. You do not open a terminal, and you do not copy the answer into the agent's window.

## Keep the Why

The next session can read the code and still undo a decision, because the code does not say which alternative lost. [Keep the Why](https://keepthewhy.com) is where a project keeps that reasoning. Maity keeps none of that reasoning in its database; the public summary it stores holds the titles, statuses and links of the entries marked for attention.

**How it works.** The entries are Markdown files in the repository, under `context/`. Each one says, in plain words, what was chosen, why, the alternatives that were rejected, and when to look at the decision again. The agents that make the changes write the entries. The hub never writes to the repository, and it never reads those files.

What the hub reads is the export the repository already publishes. Members who can read the project see it on the **Why** tab. The tab stays empty until the repository publishes that export. A public project can also show a short summary to anyone: counts, the family's members (areas or repositories), and the entries marked for attention. The summary never includes the text of an entry. The hub fills that summary in only for a project in one of the hub operator's own namespaces, and only while its last look found the repository public.

When an agent joins a project that uses Keep the Why, the hub's resume tells it how to install and load the Keep the Why skill. Unless the project turns the check off, the hub also asks the agent to confirm that it uses the skill. A code report then names the entry that holds its reason, or says why the change has none.

**An example.** This repository records why the hub uses SQLAlchemy Core and no ORM, in [SQLAlchemy Core with Table definitions, no ORM mapping](../../hub/context/persistence.md#sqlalchemy-core-with-table-definitions-no-orm-mapping).
