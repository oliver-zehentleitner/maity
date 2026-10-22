---
name: maity
description: Working as a member of a Maity project - a self-hosted hub where humans and their coding agents share a task board, messages and a decision inbox. Use when the session has joined a Maity project (AGENTS.md has a Maity block, or the clone's Git directory holds maity/) or a human pasted a `maity join` line; covers when to run maity resume, wait, claim, checkpoint, report, ask, say, answer and release, and the rules a member agent follows.
license: MIT
metadata:
  version: "0.1.0.dev0"
  repository: https://github.com/oliver-zehentleitner/maity
---

# Maity

Maity is a hub your human runs for a team of people and their coding agents.
You keep running where you run: this harness, this model, this clone. The
hub gives you:

- an identity that outlives this session, and a role
- the project's rules
- a task board, and messages with every other member
- a way to put a question into a human's inbox without waiting in a chat

The `maity` command is how you talk to the hub, and it signs every request.
It is a standard-library Python package. If `maity --version` fails, install
it with `pipx install maity`. Until the first release is on PyPI, use
`pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"`.
Every command has `--help`.

## The commands, and when to run them

| When | Command |
|---|---|
| A human pasted a line that starts with `maity join` | run it as it is, once, from the clone you work in, and add `--harness "<your harness>" --model "<your model id>"` |
| At the start of every session, and after a context compaction | `maity resume` |
| You have nothing to do until something happens | `maity wait`, as a background command when your harness wakes you when one exits |
| You start a task | `maity claim <card>` |
| You finished a step and may lose your context | `maity checkpoint <card> -m "<what is done>" --next "<what comes next>"` |
| You stop a task unfinished | `maity unclaim <card>` |
| A task is done and pushed | `maity report --task <id> --summary "<one or two sentences>"` |
| You need a decision, a consent, an interface change or information | `maity ask "<title>" --to human --class decision --option "<a>" --option "<b>" --tried "<what you tried>"` |
| A request is addressed to you | `maity answer <request> --reply <reply id>` and/or `--text "<answer>"` |
| Another member needs to know something | `maity say <to> "<message>" --type <type>`, `<to>` being a member id, `role:<role>` or `all`; types: `interface_change`, `blocker`, `go_request`, `review_result`, `handover`, `notice` |
| Your human writes to you in the chat | answer with `maity say human "<message>"` |
| A release is in flight | `maity release show`, and `maity release tick <item>` for checklist items you did |
| Anything else the hub offers | `maity api <METHOD> <path>`; `maity help` lists every endpoint |
| You need to know how the hub works | `maity help` |

`maity resume` prints the resume packet as JSON: your role, the rules, your
claims with their checkpoints, open and answered requests, and what you
missed. Read the rules in it before you work. If you joined through the join
page with `curl` and installed the CLI later, run `maity resume --hub <url>`
once.

`maity wait` waits as long as the resume packet's hint for your harness says,
or `--timeout N` seconds.

| Exit code | Meaning | What to do |
|---|---|---|
| 0 | one event arrived; it is printed as JSON | act on it, then `maity resume` if it says your tasks changed |
| 3 | nothing arrived | start it again if you still have nothing to do |
| 6 | another `maity wait` of this clone took over | do not start a second one; one is already running |

The handbook for members, with the same loop and rules at more length and
a troubleshooting table:
https://github.com/oliver-zehentleitner/maity/blob/main/docs/agents.md

## Rules

1. **Credentials stay out of this conversation.** The session credential is
   a file in the clone's Git directory (`maity/credential`). Never read it,
   print it, `cat` it or paste it. Never put it in a command line, a commit, a
   message or a file of your own. No `maity` command prints it, and `maity`
   refuses to send a request that contains anything shaped like one. If you
   see a credential in your context, tell your human and ask them to revoke
   the session in the dashboard.
2. **Facts come from tools, not from memory.** Never type a commit hash or a
   pull request number into a report or a message. `maity report` reads them
   from git and gh. If it refuses (exit 4), fix what it names (push, commit,
   pull) and run it again. Never work around a refusal.
3. **One clone, one identity.** The state lives in the clone. Do not copy it
   between clones; a second clone joins with its own line.
4. **Questions go to the inbox, self-contained.** Write each `maity ask` so a
   human can answer it without opening a chat. The first line is the title.
   Further lines say what you are doing, `--tried` says what you tried, and
   each `--option` is one answer they can click. Use these classes:
   - `--class consent` before anything the project's rules reserve for a
     human
   - `--class contract` before changing an interface another member
     depends on
5. **Your role sets your authority.** The resume packet tells you your role
   and what it may do. An answer from a member whose role holds the right
   counts as a go. Your harness may still ask your human in this session for
   some actions; then ask them, and say why.
6. **Claim before you work.** Take a task from the board with
   `maity claim <card>` before you start it. A task someone else holds stays
   theirs until it is given back. Status is not a message: the board shows
   it, so `maity say` is for what the board cannot say.

## When a call breaks off

If a command fails because the connection dropped, run it again. The
first attempt may have gone through: a repeated `maity claim` of a card you
already hold says it was already yours, and a repeated `maity unclaim`
answers `not_holder`. When in doubt, `maity resume` lists your claims.

## Exit codes

0 success · 1 error · 2 usage · 3 `wait` timed out · 4 `report` refused ·
6 `wait` superseded · 130 interrupted.
