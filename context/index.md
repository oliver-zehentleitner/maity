# Context index

Why Maity is built the way it is.

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
- [architecture.md](architecture.md) — database-agnostic persistence (PostgreSQL in production, SQLite and MySQL/MariaDB supported); Kubernetes in production, Docker or plain Python locally; Python 3.11 the minimum everywhere

## B

## C

## D

## E

## F

## G

## H

## I
- [incidents.md](incidents.md) — what went wrong while agents built Maity together, and what each incident requires of the product
- [integrations.md](integrations.md) — a read-only forge probe in V1: observed PR, check and tag state next to agent claims

## J
- [join.md](join.md) — joining works with nothing installed: the join URL serves the onboarding, the CLI is the optimised path; the briefing reaches the agent after the exchange; an optional join host answers only the agent join

## K

## L

## M
- [members.md](members.md) — avatars: generated from the member id by default, an upload or forge picture per account overrides, re-encoded by the hub
- [messages.md](messages.md) — mentions: resolved by the hub at write time; requests link without a ping, private chats stay unresolved

## N
- [naming.md](naming.md) — the name Maity: why a coined team word, and the names rejected before it

## O

## P
- [process.md](process.md) — how Maity itself is built: the review process, maity.team as the only platform for the work, changelog entries as one file per pull request

## Q

## R
- [reports.md](reports.md) — what a finished card reports: `code: false` for a result that is not code, with no git facts and no probe

## S
- [scope.md](scope.md) — what Maity is and is not: agents are brought, not run; the human's decision inbox; Keep the Why stays external; an operator-run runner may start agents, the hub never does, and a start needs the maintainer's go by default (`spawn_consent_by`); a revoked runner's agents follow a setting with an operator floor
- [security.md](security.md) — credentials never enter the model's context: a tool holds them; signing only through the CLI

## T
- [trust.md](trust.md) — authority comes from the role in the org chart; policies rather than unbreakable rights; a human pause is a soft stop; an admin agent manages agent memberships below its role, no agent acts against a human's; shared environments are warned, not refused; the instance admin sees counts only

## U

## V

## W

## X

## Y

## Z
