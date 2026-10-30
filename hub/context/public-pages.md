# Public pages

How the hub stores and serves the pages a search engine can read (`docs/api.md` §16.9).

## A public page is a row of `public_page`, served by the app shell's route

**Id:** 1e42dae2-4d67-4f1d-80b7-b2bb4aecfc3b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.9 and §16.11; the coordinator's answer of 2026-10-30 on the cards tsk-w89mspg3gwx1 and tsk-xr6fqx8e0vw5 (the stored page is a row in the database)
**Revisit when:** the pages grow so large or so many that a row per page is the wrong place, or a page has to be served from the join host

`public_page` holds one row per address: the HTML as it is served, its ETag, a digest of the inputs it
was made from and when they last changed. A page that stops being public is a deleted row
(`public_pages.remove`, `clear`), in the transaction that changed the input, so the next request already
gets the app shell. `ShellRoute` asks `public_pages.answer` before it serves the shell for a `GET` or a
`HEAD` that is no hub path: a stored page for a request without a live session or with `?as=public`,
else the shell. While `MAITY_PUBLIC_PAGES` is off, nothing is looked up. The page answers `Cache-Control:
public, max-age=60`, its ETag (`304` on a match), the CSP of the static pages and `Vary: Cookie`, never
a cookie; the shell of the same addresses carries `Vary: Cookie` too. The middleware lets a non-hub path
choose public caching while pages are on, and only the page's answer asks for it (the shell stays
`no-cache`). The page's rate limit is its own budget per source address, of the badge's size, taken
only when a page is served. The join host sends a page's address to the public root as every address
there that is not the join.

**Reason:** one row per page makes taking a page off one `DELETE` in the same transaction, and every
replica of the hub serves the same page; the route that already answers every other address is the one
place where "page or shell" can be decided without a second catch-all.

**Rejected alternatives:**
- Files on disk: deleting a file is not part of the database transaction that changed the input, so a
  page could outlive it, and replicas would need a shared volume.
- A router of its own with `/{path:path}`: registered before the `/assets` mount it would shadow the
  dashboard's files, and after the shell route it would never match.
- Rendering at request time: the contract stores the page and renders it again on change or on an
  interval, so the cost of a crawler stays one read.
- Sharing the badge's budget: the contract gives the pages the badge's size, and one visitor's pages
  and badges would then spend the same budget.
