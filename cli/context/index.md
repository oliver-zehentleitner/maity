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
- [commands.md](commands.md) — the command surface: a signed passthrough `maity api`, `--tried` on `ask`, the convenience commands (`unclaim` beside `release`), and the resume packet as text with people's text quoted; `join` prints the pointer block instead of writing it; `wait --batch` for bursts, no client-side event filter; the ticker's `more:` line repeats `--since` as the time it resolved to; `maity chat` finds a group chat's unread from the list's count, a direct one reads after the event cursor; `say --attach` deletes uploads of a refused message, `files get` renames into place after the digest check; `maity takeover` checks the objection hold and the holder before it sends; no fallback for an older hub or state before launch: a 404 is the hub's answer; shared short handles counted among the members a list shows; `maity task list` is the board, subtask refusals keep the hub's code plus one hint; a proxy's go (`--on-request`) goes only on writes, and `maity api` sends its body as read; handle arguments resolve through the member list, aliases included, an unknown name goes on to the hub, placements resolved against the member list first; `maity say` takes its message after the options; the project's full name kept in state, refreshed by every resume, a project that answers `not_found` looked up there once and followed; free text from stdin or a file, inline text the shell ate warned about; `wait` returns every pending event and filters with `--kind`; `join`/`resume` print a compact text, `--full` renders the stored packet without a second resume; unread chats in the resume, and a `wait` timeout checks them within its own deadline; `maity dormant` prints only what the hub stored for this instance, a hint and exit 0 without its entry; `jourfixe answer` takes flags or a JSON file and checks the round before it sends; request actions grouped under `maity request` so `ask` keeps free-text questions
- [credentials.md](credentials.md) — where the session credential and local state live (the clone's Git directory, never the home), another instance joined outside a clone in `<handle>#<instance>`; outgoing requests checked for credential-shaped strings; redirects refused; the hub URL from an exchange only on the given host or its direct parent; the environment ids are keyed to the stored hub URL and left out when no secret can be had

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

## N

## O

## P

## Q

## R
- [report.md](report.md) — why `maity report` refuses on any mismatch between git, the remote and the pull request, with no override; a merged pull request's head stands in for a branch deleted after the merge; the why of a code report checked locally against the last resume
- [runner.md](runner.md) — `maity runner`: a configuration that refuses unknown keys and documents every default, the CLI needs Python 3.11, one normalisation for repository entries and project URLs, what `pair` reads and refuses before sending; `serve` ends with 78 when retrying cannot help and never takes the agents with it; a placement for a harness this runner does not run is refused with a reason; deadlines are wall-clock times because they outlive the process; agents' tmux on a socket in the state directory, sessions named with underscores; Claude Code's sandbox runs strict or not at all; command allowlists are no boundary in `single`, and in `agent_user` the OS user separates the runner from the agents but not the agents from each other; `sandbox: off` until an adapter enables one; Codex reaches the operator's login through a link; Codex is confined by its sandbox and refuses command allowlists; the agents' OS user is the operator's choice; for now Claude Code and Codex only; model access is the operator's; default modes: Claude Code attachable, Codex woken by events; `stop-all` refuses while the service runs, `gc` never holds an agent's credential; sandboxed agents: git redirects pinned, other clones and secrets unreadable; in the agent_user layout the agents' side belongs to the agents' user; on the ssh backend each host is a target that runs its own `maity`; a placement without a target stays on the host it was first given; a provider limit reaches the runner as the loop's exit 22, and no harness signals one yet; the runner tells the agent's resume it is supervised through MAITY_SUPERVISOR; workspaces keyed on the project id, a clone from before the namespace taken over in place, the configured projects as full names or aliases

## S

## T

## U

## V

## W

## X

## Y

## Z
