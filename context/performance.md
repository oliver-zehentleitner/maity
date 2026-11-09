# Performance

How fast the dashboard is meant to be, what is known to make it slow, and the list of
measures kept for later.

## Dashboard pages aim at about 1 s, and the measures are worked through from the biggest expected gain

**Id:** f81ab39d-1f35-40e2-bf25-aea0fa6fb102
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's answers to two inbox requests, 2026-11-08 (the goal of about 1 s per page; a kept list of every measure, worked from the biggest expected gain); umbrella card tsk-a5pxwgkgr73e and its step-1 notes, built from the hub's request log and local statement counts
**Revisit when:** a page meets the goal on a cold load, or a measure on the list turns out to cost more than it gains

Every dashboard view (inbox, board, card panel, chat, members, settings, public pages)
should be usable within about 1 s with a warm cache, and a cold load should come as close
as it can. The measures below are kept as a list and done in order of expected gain until
the pages fit. Each one is its own card and pull request. Measures that change the API
contract go to the owner first.

Measured on 2026-11-08 from the hub's request log and local statement counts:

- **Cold load, every page:** 100–106 script and style files, all fetched again (never a
  304) in 4 waves as the browser finds each ES module's imports. The last file arrives
  3.2–5.1 s after the HTML.
- **Inbox:** 3 request pages one after another, 1.1–1.9 s each. About 6 statements per
  request: 1,219 for a page of 200.
- **Board:** all cards (1,135) in 6 pages of 200, one after another, 1.4–2.8 s.
- **Members page:** the credentials are read once per member (27 at once), about 1.2 s.
- **Card panel and chat:** fast on the server, but `…/members` and the chat list are read
  again every 0.4–3 s.
- **Flat per row** (3 vs 30 rows): every other list.
- **Baseline with a test account** (headless browser, median of 3 runs, cold and warm):
  the load event at 0.7–0.8 s on every page, warm no faster than cold, because all 101–103
  files come back 200 on a reload. The board and a card's panel end at 2.9–3.4 s: about 28
  avatar reads per page, 300–500 ms each as they queue. On a reload they answer 304, but
  each one is still a round trip.

The list, in the order agreed (gain is the expected share of a page's time):

| # | Measure | Gain | Cost | Status, card |
|---|---|---|---|---|
| 1 | Caching: content-hashed files `immutable`, ETag/304 on avatars and reads | warm load without ~100 requests and their waves | M | in progress, tsk-pcw785rhymyg |
| 1a | Avatars cached for good: every `avatar_url` already names its version (`?v=…`), so its answer can be `immutable` | board and card −1.5–2 s warm | S | tsk-vvyqmk9vwg8e |
| 2 | One load wave: `modulepreload` for every module in the HTML | cold load −2–4 s | M | card to come |
| 3 | A page of requests in one batch | inbox −~4 s | S | done, tsk-fxjtwmkc4md5 (#1515) |
| 4 | The inbox reads open requests first, the history on demand | inbox −1–2 s | S | tsk-y8gkq1kvt63c |
| 5 | The board without serial paging (open cards first, closed window later) | board −1 s | S–M | tsk-d61rvjm6gteh |
| 6 | The members page reads credentials on expand, not per member up front | members −0.5 s, 26 requests | S | tsk-d61rvjm6gteh |
| 7 | The repeated reads (card panel `…/members`, chat list) found and stopped | load on every page | S | tsk-d61rvjm6gteh |
| 8 | A chat's messages: senders and first deliveries in one statement each | −~0.1 s per chat | S | tsk-239r9cwxje6w |
| 9 | `Server-Timing` on the instance admin's API answers (statements, database time, total) | the yardstick for the rest | S | tsk-239r9cwxje6w |
| 10 | One boot read: `/me`, the session, the project and its members in one answer | −0.3–0.6 s per full load | M, contract | with the owner |
| 11 | Bundling the scripts with a build step | beyond item 2, if still needed | L | later |
| 12 | Indexes for the hot queries, from EXPLAIN on PostgreSQL with a seeded copy of the shape | unknown | M | later |
| 13 | Response size: fields the lists do not need, compression of API answers checked | unknown | S to measure, contract to trim | later |
| 14 | Render cost in the browser, from a performance trace of the board and a chat | unknown | S to measure | later |
| 15 | A statement test per list route, and a check on the number and size of the files the HTML loads, in CI | keeps the gains | S | later |

**Reason:** the owner set the goal and the order. Working by expected gain puts the shared
cold-load cost first, since every page pays it. A kept list lets a measure that is not done
now be picked up later without measuring again from scratch.

**Rejected alternatives:**
- Bundling the scripts first: the owner's order puts the one load wave first and keeps
  bundling for later, if it is still needed. A `modulepreload` list needs no build step,
  which the project does not have.

## `Server-Timing` for the instance admin only, with counts and durations only

**Id:** 245e1465-b689-4930-a6de-63a38886dc0f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-239r9cwxje6w and its plan note, approved by the lead, 2026-11-08; the audience narrowed and the log line added on the lead's word, 2026-11-09, after a review of pull request #1542 measured the leak below
**Revisit when:** a measurement needs the header for an account that is not the instance admin, or the header must name more than counts and durations

Every API answer whose cookie sign-in admits the instance admin (the earliest account,
`maity_hub.admin.instance_admin_id`) carries
`Server-Timing: db;dur=<ms>, sql;desc="n=<count>", total;dur=<ms>`, on any status, a
second-factor refusal included. A route that signs nobody in (the health probe, the help)
and an unknown route carry none. No other caller gets it: not another human, not an agent,
not a token, not a visitor. A measurement on prod therefore runs signed in as the instance
admin; a test account sees no header. Whether the caller is the instance admin is a column
of the sign-in's own read of the session and the account, so it costs no statement of its
own.
Every API request also writes the same numbers to the hub's log (`maity_hub.timing`:
`route=<pattern> status=<code> sql=<count> db_ms=<ms> total_ms=<ms> pid=<worker>`), which
only the operators read: the route's pattern, never the path, so the line adds no handle or
id; the pid ties a slow line to the worker that answered it. The
values are taken when the answer starts. A long poll's wait counts in `total` and never in
`db`. The tally is a context variable set by the outermost middleware (`maity_hub.timing`),
so the hub's own checks before a route count too; the cookie sign-in marks it as shown. The
cursor events of the engines (the pool's, the write guard's and the health probe's own)
add to it, and outside a request they add nothing.

**Reason:** a slow page has to be split into its calls, and each call into database time
and the rest, by whoever measures it: in the browser's network panel, or for every account in the log. Until now only the
server log showed a call's time, and nothing showed its statement count. The statement
count is kept because it is the cheapest way to see an N+1. But a count or a duration on an
answer depends on data the caller may not see: a signed-in stranger's read of a person
answered the same empty agent list while the count rose by 3 for each agent the person had
in a private project (27, 30, 33, 36 for 0 to 3 agents, on PostgreSQL). So only the
instance admin, who measures and may read the instance's metadata anyway, gets it.

**Rejected alternatives:**
- The header on every success, and none on a refusal (the first version of #1542): the
  measured leak above is on a 200.
- The header for every signed-in human: the leak was measured with a signed-in stranger.
- An operator switch, off by default, with the header for everyone where it is on: prod is
  where the slow pages are, and there it would have to stay off.
- Durations only, no count: a duration leaks the same, only noisier, and it loses the N+1
  signal.
