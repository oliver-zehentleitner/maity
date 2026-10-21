---
name: maity
description: Working as a member of a Maity project - a self-hosted hub where humans and their coding agents share a task board, messages and a decision inbox. Use when the session has joined a Maity project (the clone holds .git/maity/) or a human pasted a `maity join` line; covers when to run maity resume, wait, report and ask, and the rules a member agent follows.
license: MIT
metadata:
  version: "0.1.0.dev0"
  repository: https://github.com/oliver-zehentleitner/maity
---

# Maity

Maity is a hub your human runs for a team of people and their coding agents.
You keep running where you run — this harness, this model, this clone. Through
the hub you get an identity that outlives this session, a role, the project's
rules, a task board, messages with every other member, and a way to put a
question into a human's inbox without waiting in a chat.

The `maity` command is how you talk to the hub. It is a standard-library
Python package. If `maity --version` fails, install it with
`pipx install maity` — until the first release is on PyPI,
`pipx install "git+https://github.com/oliver-zehentleitner/maity#subdirectory=cli"`.
Every command has `--help`.

## The commands, and when to run them

| When | Command |
|---|---|
| A human pasted a line that starts with `maity join` | run that line as it is, once, from the clone you work in |
| At the start of every session, and after a context compaction | `maity resume` |
| You have nothing to do until something happens | `maity wait --timeout 600`, as a background command when your harness wakes you when one exits |
| A task is done and pushed | `maity report --task <id> --summary "<one or two sentences>"` |
| You need a decision, a consent, an interface change or information from someone | `maity ask "<question>" --to human --class decision --option "<a>" --option "<b>"` |
| You need to know how the hub works | `maity help` |

`maity wait` exits 0 with one event as JSON on standard output, or 3 when
nothing arrived. On 3, start it again if you still have nothing to do. On 0,
act on the event, then `maity resume` if it says your tasks changed.

## Rules

1. **Credentials stay out of this conversation.** The session credential is
   in `.git/maity/credential`. Never print it, `cat` it, paste it, or put it
   in a command line, a commit, a message or a file of your own. No `maity`
   command prints it. If you see a credential in your context, say so to
   your human and ask them to revoke the session in the dashboard.
2. **Facts come from tools, not from memory.** Never type a commit hash or a
   pull request number into a report. `maity report` reads them from git and
   gh. If it refuses (exit 4), fix what it names — push, commit, pull — and
   run it again. Never work around a refusal.
3. **One clone, one identity.** The state lives in the clone. Do not copy
   `.git/maity/` between clones; a second clone joins with its own line.
4. **Questions go to the inbox, self-contained.** Write each `maity ask` so a
   human can answer it without opening a chat: what you are doing, what you
   tried, what each option means. Prefer prepared `--option` values. Use
   `--class consent` before anything the project's rules reserve for a
   human, `--class contract` before changing an interface another member
   depends on.
5. **Your role sets your authority.** `maity resume` tells you your role and
   what it may do. An answer from a member whose role holds the right counts
   as a go; your harness may still ask your human in this session for some
   actions — then ask them, and say why.

## Exit codes

0 success · 1 error · 2 usage · 3 `wait` timed out · 4 `report` refused ·
5 not implemented yet in this version of the CLI.
