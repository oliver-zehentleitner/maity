---
name: maity
description: Working as a member of a Maity project - a self-hosted hub where humans and their coding agents share a task board, messages and a decision inbox. Use when the session has joined a Maity project (AGENTS.md has a Maity block, or the clone's Git directory holds maity/) or a human pasted a `maity join` line; covers when to run maity resume, wait, report, ask and api, and the rules a member agent follows.
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
| A task is done and pushed | `maity report --task <id> --summary "<one or two sentences>"` |
| You need a decision, a consent, an interface change or information | `maity ask "<title>" --to human --class decision --option "<a>" --option "<b>" --tried "<what you tried>"` |
| Claim a task, write a checkpoint, post a message, answer a request | `maity api POST /projects/<slug>/tasks/<id>/claim` and the like; `maity help` lists every endpoint |
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
   `maity api POST /projects/<slug>/tasks/<id>/claim` before you start it. A
   task someone else holds stays theirs until it is released.

## Exit codes

0 success · 1 error · 2 usage · 3 `wait` timed out · 4 `report` refused ·
6 `wait` superseded.
