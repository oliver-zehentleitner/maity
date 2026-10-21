# Fixtures

## Fixture mode: JSON files shaped like the API, a committed bundle for file://, no silent fallback

**Id:** 19d4c8bf-f100-479a-a052-12d3c7fd48ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's task brief, 2026-10-21; the dashboard's first implementation, 2026-10-21
**Revisit when:** `docs/api.md` is published and the hub answers every endpoint the views use — fixture mode then becomes a development aid only

The views read through one small fetch layer (`js/api.js`) that answers
either from `/api/v1/...` or from fixtures. The fixtures are JSON files in
`web/fixtures/`, one per endpoint, shaped like the API answer the views
expect, so they can be diffed against the contract when it lands.
Because a page opened from `file://` cannot `fetch()` a local file,
`tools/check.py --write` also generates `fixtures/fixtures.js`, which
holds the same JSON in one global; it is committed and `make check` fails
when it is stale. The source is chosen once per page load: `file://`
means fixtures, a page served over HTTP means the API, `?source=` forces
either. When the API fails, the page says so on screen; it never falls
back to fixtures on its own, and fixture mode is labelled on every screen.

**Reason:** the brief asks for a page that renders before the API exists
and that opens from the file system; JSON keeps the fixtures readable as a
contract proposal for the server's owner. The no-fallback rule follows
from what the dashboard is for: the human answers agents' requests from
it, and an answer given to a fixture shown as if it were live is lost
without anyone noticing.

**Rejected alternative:** fetching the JSON files directly — fails on
`file://`. Requiring a local web server during development — contradicts
the file-system requirement. Fixtures written only as JavaScript — loses
the plain JSON the API contract is reconciled against. A fallback from a
failing API to fixtures — rejected for the reason above.
