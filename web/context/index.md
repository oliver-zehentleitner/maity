# Context index

Why the Maity dashboard (`web/`) is built the way it is. Family-wide decisions are in the root [`context/`](../../context/index.md).

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

## D

## E

## F
- [fixtures.md](fixtures.md) — fixture mode only on file://: JSON in the API's shapes, a committed bundle, no switch on an http(s) origin

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
- [refresh.md](refresh.md) — the project's events read with wait=0 every 5 s from after=latest, not the long-poll; presence re-read in place
- [rendering.md](rendering.md) — agent-written text is rendered as text only, enforced by make check; links from data https only; credential values never shown, the join line only in its view; pictures set on the account, no pre-upload preview; attachments: images from the hub's path, files only as downloads

## S
- [stack.md](stack.md) — no framework and no build step: static HTML, vanilla JS as classic scripts so the page also opens from file://; the smoke test on a bare node binary; a real-browser end-to-end test with Playwright for Python in CI; accessibility checked with axe-core from its pinned npm tarball

## T

## U

## V
- [views.md](views.md) — the inbox is the first screen, then board, agents, organisation, chat; a project switcher everywhere and the cross-project inbox as landing page; the org tree is computed, never stored; project messages read from the events until the hub has §8.8

## W

## X

## Y

## Z
