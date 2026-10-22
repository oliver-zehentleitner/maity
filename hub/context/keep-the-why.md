# Keep the Why export

## The export lives in memory, read on request and refreshed in the background for the view

**Id:** f5af1bd9-bb11-4310-b751-334de2668dfe
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-22 (docs/api.md §11.3), with the hub owner's notes on caches
**See:** outbound.md#reads-whose-host-comes-from-data-connect-to-the-address-that-was-checked — a196b7db-8af0-4863-8852-031d4dbb35f8 — as of 2026-10-22
**Revisit when:** a second replica runs (each would read the families on its own), or the families grow so large that a cold read after a restart is felt

`ktw.Cache` holds, per project, the last read of the whole family and
each member's last good export.
- **The endpoint** reads through when the entry is older than `max_age`.
  It takes one lock per project, so concurrent requests share the read.
- **A forced read** (`max_age=0`) within 30 seconds of the last one is
  answered from the cache.
- **The project view** only reads the cache. A missing or stale entry
  schedules one background read per project on a pool of two threads,
  so a view built right after a restart shows `null` until that read
  lands.
- **What is stored:** the summaries and the entries that need
  attention, cleaned, never the export itself.
- **Ending:** all of it ends with the process.
- **Budget:** one read of a family has 30 seconds, configs and exports
  together. A member not read by then is `timeout`. A request that waits
  longer than that for another request's read gets the cached answer,
  or `503` when there is none. Anyone who can push to the repository
  could otherwise name a slow host and tie up threads.

**Reason:**
- §11.3 forbids storing the export: Keep the Why stays external, and
  the database holds nothing from `context/`.
- A view must never wait on up to 32 outbound reads, nor let anyone who
  can list projects trigger them in the request.
- A restart is rare, and the first request after it reads the family
  anyway.

**Rejected alternatives:**
- A table for the summaries: against §11.3 and its rule that only the
  cache keeps entries.
- Reading the family inside the project view when the cache is stale:
  up to 32 reads of 10 seconds behind a page load.
- The probe's worker sweeping all families: it exists only with a
  forge token, and a public repository's families are readable without
  one.
