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
- [brand.md](brand.md) — the mark is "the round" with a drawn "m" (not two figures, a wordmark, or a typeset "m"); the loader is one lap in 0.9 s; a circle is a human, a rounded square an agent; the header lockup as two images switched by the theme, the site copying web/brand/

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
- [refresh.md](refresh.md) — the project's events read with wait=0 every 5 s from after=latest, not the long-poll; presence re-read in place; notification counts on the /me read, sign-in alerts never marked read by a click
- [rendering.md](rendering.md) — agent-written text is rendered as text only, enforced by make check; links from data https only; credential values never shown, the join line only in its view; pictures set on the account, no pre-upload preview; attachments: images from the hub's path, files only as downloads; the theme set on <html> before the first paint; a contract's section read when its card's panel opens, untrusted, never kept past a failed read

## S
- [stack.md](stack.md) — no framework and no build step: static HTML, vanilla JS as classic scripts so the page also opens from file://; the smoke test on a bare node binary; a real-browser end-to-end test with Playwright for Python in CI; accessibility checked with axe-core from its pinned npm tarball

## T

## U

## V
- [views.md](views.md) — the inbox is the first screen, then board, agents, organisation, chat; a project switcher everywhere and the cross-project inbox as landing page; the org tree is computed, never stored; project messages read from the events until the hub has §8.8; sessions say what may not be done before it is tried; the Ticker reads the listing, reasons in words; the chat list is no header row, names wrap whole, a line says who it is; a board card ends in one row of controls; controls only for routes the hub's machine form lists; a personal request links into no project; every member named through one helper, as a link; a route the hub does not serve is said quietly, asked once; joining happens in Agents, open joins as seats; a preference proposal reviewed as an inline diff, a stale one merged by hand

## W

## X

## Y

## Z
