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
- [commands.md](commands.md) — the command surface: a signed passthrough `maity api`, `--tried` on `ask`, the convenience commands (`unclaim` beside `release`), and the resume packet as text with people's text quoted; `join` prints the pointer block instead of writing it; `wait --batch` for bursts, no client-side event filter
- [credentials.md](credentials.md) — where the session credential and local state live (the clone's Git directory, never the home); outgoing requests checked for credential-shaped strings; redirects refused; the hub URL from an exchange only on the given host or its direct parent

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
- [report.md](report.md) — why `maity report` refuses on any mismatch between git, the remote and the pull request, with no override
- [runner.md](runner.md) — `maity runner`: a configuration that refuses unknown keys and documents every default, tomllib only from 3.11, one normalisation for repository entries and project URLs, what `pair` reads and refuses before sending; `serve` ends with 78 when retrying cannot help and never takes the agents with it; a placement the runner cannot act on yet is logged, not reported as a failure; deadlines are wall-clock times because they outlive the process; agents' tmux on a socket in the state directory, sessions named with underscores; Claude Code's sandbox runs strict or not at all; command allowlists are no boundary until agents run as their own user; `sandbox: off` until an adapter enables one; Codex reaches the operator's login through a link

## S

## T

## U

## V

## W

## X

## Y

## Z
