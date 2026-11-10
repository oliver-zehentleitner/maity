# Ticker

## The Ticker view reads the listing, not the events, and says each reason in the dashboard's own words

**Id:** 6c688878-105b-4162-b0ad-5e1302df921c
**Type:** decision
**Status:** needs-review
**Evidence:** inferred
**Source:** docs/api.md §17.5 (shaped per reader), §17.6 (manual post), §17.8 (subscriptions) and §17.9 (listing and the dashboard's part); the coordinator's card for the Ticker view (tsk-sbx670wtr5qb), 2026-10-23; the dashboard's implementation against the mock, 2026-10-23
**Revisit when:** the hub serves `/ticker`, or the listing gains a field the view now derives
**See:** refresh.md#the-dashboard-reads-the-projects-events-with-wait0-on-an-interval-not-with-the-long-poll — 264c1452-2cc4-4518-b1fb-85e901a09aa2 — as of 2026-10-23

The Ticker tab reads `GET …/ticker` (`for=me` by default, `type`, `area`,
the hub's cursor) and shows the listing's compact items as they come,
shaped for this reader by the hub. A ticker event in the project's feed
is only the signal: the view reads its own listing after the newest item
it shows (`after=`, oldest first, page by page), with the same filters,
and puts what it has not shown on top. Every read belongs to one filter
set, and an answer that arrives after the filters changed is dropped. A
404 is an error (until 2026-10-30 it meant "no ticker" when the hub's
`openapi.json` lacked the path, e1699490). Reasons are shown as
words ("you own hub/", "you implement §13"), not as the API's tokens. A
manual post to everyone asks first, since it wakes every member who has
not muted it.

**Reason:** the listing is the one form the hub shapes per reader and
per filter (`for_me`, `why`, `muted`, a decision withheld from a
non-reader); building items from the raw events would mean redoing that
shaping in the page, and getting a decision's visibility wrong would
show a reader something the hub hides. §17.9 leaves the words to the
dashboard. A post to everyone is the one action here that wakes the
whole team.

**Rejected alternative:** reading the newest page again on each event:
when more than a page of items arrives at once (a reconnect, a burst of
deploys), the ones in between are never shown until a reload. Building
items from the raw events: the per-reader shaping would have to be
redone in the page. Taking any 404 on the listing as "no ticker": §17.6
notes that a mistyped project answers the same. Showing the reason
tokens as they are: they are the CLI's text form, not words for a
person.


## The ticker's contract implementers are edited as lines of text

**Id:** b1c60ee1-addd-4e0f-897c-937fcdea8b29
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's wish for ticker settings in Project settings (tsk-a3cj2canahy3), 2026-10-27; docs/api.md §17.3 (a map of up to 200 sections to up to 20 tokens each, `*` for the rest, the view to show unresolved tokens); the dashboard's implementation, 2026-10-27
**Revisit when:** the mapping grows past what a textarea reads well, or the hub validates and names unresolved tokens itself

`settings.ticker.contract_implementers` is a textarea of lines
`<section>: <token> <token>`, the contract's own notation; the form
checks each line and token before sending, sends the setting whole, and
says the tokens that name nobody now (a member not in the project, a
role nobody holds, an area no member owns) under the field.

**Reason:** the mapping is a list a maintainer writes once and reads
often; lines match how the contract writes it and how a reviewer would
paste it, and 200 sections fit.

**Rejected alternative:** a row per section with pickers for areas,
members, roles and trusts: many controls for a short list, and it could
not hold a token that names nobody yet, which the hub accepts.
