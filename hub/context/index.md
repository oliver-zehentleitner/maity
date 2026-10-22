# Context index

Why the hub (`hub/`, the server) is built the way it is. Family-wide decisions are in the root [`context/`](../../context/index.md).

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
- [auth.md](auth.md) — a call's presence and lease side effects commit before the endpoint runs

## B

## C

## D

## E
- [events.md](events.md) — the long-poll waits on an asyncio event in-process, never on the database

## F

## G

## H

## I

## J
- [joins.md](joins.md) — the join page's HTML via markdown-it-py with raw HTML off; the template shipped from docs/ into the wheel

## K

## L

## M

## N

## O

## P
- [packaging.md](packaging.md) — `src/` layout with migrations and `/help` as package data; all three drivers by default; the image's SQLite data volume; the tested set pinned with hashes via `uv pip compile --universal`
- [persistence.md](persistence.md) — SQLAlchemy Core without the ORM; explicit migrations; at-most-one markers; value sets in the API; ids; JSON columns; UTC timestamps; utf8mb4_bin on MySQL; SQLite WAL

## Q

## R

## S
- [serving.md](serving.md) — dashboard optional unless configured explicitly, no dotfiles; local bind by default; no CDN-loaded Swagger UI

## T
- [testing.md](testing.md) — CI matrix: full check on SQLite, tests on PostgreSQL 17 and MariaDB 11.4; MariaDB stands in for MySQL

## U

## V

## W

## X

## Y

## Z
