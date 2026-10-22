# AGENTS.md

Maity is a self-hosted hub where humans and their independently running
coding agents join shared projects: identity, roles, a task board, messages,
organisation models, and one decision inbox for the human. Agents are
brought, not run — the hub never starts or owns an agent process.

- What it is and is not: `README.md`
- How it fits together: `docs/` (grows with the design)
- Why it is built this way: `context/index.md`
- What is open and who does what: `TASKS.md`
- If `AGENTS.local.md` exists in this checkout, read that too: personal notes, not committed

## How we work

- Work lands as a pull request against `main`; branches are named
  `<who>/<topic>`. Nothing is pushed to `main` directly after the initial
  scaffold.
- Before starting work and before opening a pull request: fetch `main` and
  read `context/index.md` and the topics you touch. A decision recorded there
  was argued once already; propose a change to it, do not silently revert it.
- Documentation is part of the change: README, CHANGELOG under
  `[Unreleased]`, `docs/` and `context/` are updated in the same pull request
  as the code they describe. A `context/` entry is committed right after it is
  written, in its own commit, so that its Git timestamp is the moment the
  reasoning was recorded.
- Language: code, comments, commits, docs and `context/` in English.
- Secrets never enter the repository.

## Keep the Why

This project records the reasoning behind its code with the Keep the Why
skill (https://keepthewhy.com) — the `.keep-the-why` file at the project
root is its config. Before doing anything else in a session, whatever the
first request is about, load the skill: in Claude Code, invoke the
`keep-the-why` skill (Skill tool); in any other agent, read
`.claude/skills/keep-the-why/SKILL.md` and follow it, including the
`references/*.md` files it points to for the situation at hand.
The skill is not vendored in this repository. If your agent has no
installed copy, install it once with
`npx skills add https://github.com/oliver-zehentleitner/keep-the-why/tree/latest/skills/keep-the-why`
(it lands in `.claude/skills/keep-the-why/` or your agent's skills
directory), or read it at
https://github.com/oliver-zehentleitner/keep-the-why/tree/latest/skills/keep-the-why.
