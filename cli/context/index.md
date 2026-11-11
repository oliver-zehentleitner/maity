# Context index

Why the Maity CLI and the agent skill are built the way they are.

## 0

## 1

## 2

## 3

## 4

## 5

## 6

## 7

## 8

## 9

## A

## B

## C
- [commands.md](commands.md) — the command surface: `say --review-file` checks the cites and the message's text at the head, a quote only where the text ties it to one file, a ratio is not a file and line, a Keep-the-Why id is the full UUID at the head, any other hyphenated hex token with a letter a-f is refused, and a cited test, including path::name, is a def or async def of that name there, `say --type update` without a recipient, a signed passthrough `maity api`, `--tried` on `ask`, the convenience commands (`unclaim` beside `release`), `claim renew` renewing all of the instance's claims with a card only filtering what it prints (not built yet), and the resume packet as text with people's text quoted; `join` prints the pointer block instead of writing it; `wait --batch` for bursts, no client-side event filter; the ticker's `more:` line repeats `--since` as the time it resolved to; `maity chat` finds a group chat's unread from the list's count, a direct one reads after the event cursor; `say --attach` deletes uploads of a refused message, `files get` renames into place after the digest check; `maity takeover` checks the holder before it answers; no fallback for an older hub or state before launch: a 404 is the hub's answer; shared short handles counted among the members a list shows; `maity task list` is the board, subtask refusals keep the hub's code plus one hint; a proxy's go (`--on-request`) goes only on writes, and `maity api` sends its body as read; handle arguments resolve through the member list, aliases included, an unknown name goes on to the hub, placements resolved against the member list first; `maity say` takes its message after the options; the project's full name kept in state, refreshed by every resume, a project that answers `not_found` looked up there once and followed; free text from stdin or a file, inline text the shell ate warned about; `wait` returns every pending event and filters with `--kind`; `join`/`resume` print a compact text, `--full` renders the stored packet without a second resume; unread chats in the resume, and a `wait` timeout checks them within its own deadline; each `wait` long-poll leaves the hub 10 s to answer, the last read running out ends the window quietly; `wait` retries a 429 like a 5xx, at least its `Retry-After`; the lead on a line of its own and, with siblings, whom to ask before taking or handing over work; `maity dormant` prints only what the hub stored for this instance, a hint and exit 0 without its entry; `jourfixe answer` takes flags or a JSON file and checks the round before it sends; `maity jourfixe` reads every series, `answer` takes the unanswered round that closes first; request actions grouped under `maity request` so `ask` keeps free-text questions; the moderator's statement and report are sent as read from a JSON file; `join` ends with how to put `maity` on PATH; `join` ends with the chat to the agent's human, after a resume only; without a briefing it points at the hand-over, a takeover is named in the check-in block; `--for` refused by the client on any `/me` path, `wait --for` keeps a cursor per served agent; a cross-project group chat is named on resume with its GET, not a command of its own; `wait` resolves `--for` and its cursor inside the loop's retry; `wait` names a message's attachments and gives `maity files get <id>` without `-o`
- [credentials.md](credentials.md) — where the session credential and local state live (the clone's Git directory, never the home), the access list that replaces mode bits on Windows and the full runner staying off it, while local mode runs there natively; another user's file refused with the way out, no fix command; a leading byte order mark dropped from every text input, another instance joined outside a clone in `<handle>#<instance>`; outgoing requests checked for credential-shaped strings; redirects refused; the hub URL from an exchange only on the given host or its direct parent; the environment ids are keyed to the stored hub URL and left out when no secret can be had; a join that fails leaves the directories it created: removal by path cannot be bound to their identity

## D

## E

## F

## G

## H

## I

## J

## K

## L

## M
- [maintenance.md](maintenance.md) — `maity wait` sleeps a maintenance window out with jitter, every other command exits 7

## N

## O

## P

## Q

## R
- [report.md](report.md) — why `maity report` refuses on any mismatch between git, the remote and the pull request, with no override; a merged pull request's head stands in for a branch deleted after the merge; the why of a code report checked locally against the last resume; what maity hands to git and gh is checked first, git's transports fixed through the environment; without a working gh the card's linked pull request is read through the hub's probe, its head matched exactly; a pull request that does not name the card is shown with its title and confirmed (`--yes` without a terminal); a branch that tracks the remote's default branch is set to track its own branch of that name before the report, when the remote has it; a branch without an upstream is read as its own branch on the push remote
- [runner.md](runner.md) — `maity runner`: a configuration that refuses unknown keys and documents every default, the CLI needs Python 3.11, one normalisation for repository entries and project URLs, what `pair` reads and refuses before sending; `serve` ends with 78 when retrying cannot help and never takes the agents with it; a placement for a harness this runner does not run is refused with a reason; deadlines are wall-clock times because they outlive the process; agents' tmux on a socket in the state directory, sessions named with underscores; Claude Code's sandbox runs strict or not at all; command allowlists are no boundary in `single`, and in `agent_user` the OS user separates the runner from the agents but not the agents from each other; `sandbox: off` until an adapter enables one; Codex reaches the operator's login through a link; Codex is confined by its sandbox and refuses command allowlists; the agents' OS user is the operator's choice; for now Claude Code and Codex only; model access is the operator's; default modes: Claude Code attachable, Codex woken by events; `stop-all` refuses while the service runs, `gc` never holds an agent's credential; sandboxed agents: git redirects pinned, other clones and secrets unreadable; in the agent_user layout the agents' side belongs to the agents' user; on the ssh backend each host is a target that runs its own `maity`; a placement without a target stays on the host it was first given; a provider limit reaches the runner as the loop's exit 22, and no harness signals one yet; the runner records Claude Code's folder trust for the clone before an interactive start, under Claude Code's own lock; the runner tells the agent's resume it is supervised through MAITY_SUPERVISOR; a headless placement is offered no tool for asking a person; `maity runner install` sets up the system service at fixed paths, refusing what it did not make (an incomplete configuration is enabled, not started), and `uninstall` removes nothing until the agents are known to be stopped; workspaces keyed on the project id, the configured projects as full names or aliases; local mode runs one agent in the foreground without pairing, also on Windows, with a runner's adapter context and the files outside the workspace, Git only in a fresh directory and a harness only after a complete checkout, one lock per workspace path outside every renamed directory, held by local mode alone (a run that outlives it is not covered yet), a retry's copy starts only at the one path its mark names, compared by identity (one copy at a time; a leftover renamed onto a path freed later, or a `.replaced-*` made by hand, is not covered), and a stopped local mode counts as not listening; under the runner, maity's own git runs only in the runner's clone (from `GIT_COMMON_DIR`), checked as `gc` checks it; a failed clone says why in the runner's log, the report keeps only the codes; only a supervised placement sends `MAITY_SUPERVISOR`; sandboxed git works without writing `.git/config`, the sandbox's placeholders hidden in `.git/info/exclude`

## S

## T

## U

## V
- [version.md](version.md) — release version beside build identity: packages freeze revision and dirty state, source checkouts show their current revision, the hub names the published CLI so an older one warns, and a source archive keeps its stamp when rebuilt

## W

## X

## Y

## Z
