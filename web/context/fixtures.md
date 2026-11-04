# Fixtures

## Fixture mode: JSON files shaped like the API, a committed bundle for file://, no silent fallback

**Id:** 19d4c8bf-f100-479a-a052-12d3c7fd48ed
**Type:** decision
**Status:** superseded
**Superseded by:** beba53ac-5380-42e4-bae7-fbc33afe83ed
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

## Fixture mode only on file://: an http(s) origin never loads the fixtures

**Id:** beba53ac-5380-42e4-bae7-fbc33afe83ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's review of the dashboard pull request, 2026-10-21
**Revisit when:** development needs fixture data on an http origin, for example to test with a real browser's CSP — then a flag the hub cannot serve, not a query parameter

The views read through `js/api.js`, which answers from `/api/v1/...` or,
only when the page was opened from the file system, from the fixtures in
`web/fixtures/`: one JSON file per endpoint in the shapes of
`docs/api.md`, plus the generated `fixtures/fixtures.js` bundle that
`make check` keeps current, because `file://` cannot `fetch()` JSON. The
bundle is not referenced from `index.html`; `api.js` loads it on the
first fixture request, so a page served over HTTP never has it. There is
no query parameter or other switch into fixture mode, an API error
offers no way into it, and fixture mode is labelled on every screen.

**Reason:** the hub serves this directory at `/`, so whatever switch a
developer could use would also work on the production origin. A human
who reached fixture mode there — from an error page's link, a bookmark,
a pasted URL — would answer fixture requests and believe the agents got
the answers. The earlier rule "never fall back to fixtures on its own"
stopped the silent case but not the one-click one.

**Rejected alternative:** `?source=fixtures` on any origin, the previous
entry's design — the case above. A development flag the hub never serves
(a dotfile, a header) — workable, but `file://` already covers
development, and every extra switch is one more thing to keep out of
production.

## The fixtures' shapes are compared with recorded hub answers, not with response models

**Id:** a1733a10-7836-48d8-930e-ba4a85aa72ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-eqgmjm5vcwam and the lead's approval of its plan, 2026-11-02
**Revisit when:** the hub declares response models on its routes — then the check can read the models' schema instead of a recorded file

`hub/tests/test_web_shapes.py` seeds a project, sends the requests listed
in `web/tools/shape-requests.json` and records the form of each answer
(keys and types, items of lists merged, `maps` for objects whose keys are
data) in `web/tools/hub-shapes.json`; the test fails when the hub's
answers no longer match that file, and `make -C web shapes` records it
again. `tools/check.py` sends the same requests to the fixture hub
(`tools/fixture_answers.js`, which runs `js/api.js` on the fixtures) and
reports every difference that is not in
`tools/fixture-shapes-baseline.json`: a key the fixture has and the hub
does not, a key the hub has and the fixture lacks, another type. The
baseline holds today's differences; for a request already listed it only
shrinks (`make fixtures` drops what no longer differs); a request added
to the list has its differences written into the baseline by hand, since
`--write` only drops entries. Writes (`POST` and `PATCH` with the
request's `body`, and `DELETE`) come after every read in the list, and
the hub test fails on a read after a write: both sides send the requests
in order to one seed, so a read sees the seed before any write changed it. It started with about ten routes; more
come one at a time, and a test keeps the two copies of the form functions
(the hub test's and `check.py`'s, which uses the standard library only)
equal.

**Reason:** the hub declares no `response_model`; its answers are dicts
built by view functions. A check against models would first need models
for about 200 routes, a hub-wide change for a web check. And the fixture
answers are not only the JSON files: `js/api.js` computes them in about
220 handlers, so comparing JSON files with a schema would miss most of
what the dashboard reads in fixture mode. Recording keeps the hub
unchanged and compares what each side actually answers.

**Rejected alternative:** response models on every hub route — the cost
above. Comparing the fixture JSON files with `docs/api.md` — the
contract is prose, and the files are not the answers. Treating every
missing key as a finding at once — about 80 today; the baseline lets the
check land and the fixtures catch up route by route.

**Consequence:** a key the hub sends only in some states is missing
from the record when the seed lacks that state, and an empty list says
nothing about its items. So the seed fills what is cheap: settings,
mentions, a note, a link, a dependency, a request. `banner.etag` and
`logo.etag` (only with an image) stay in the baseline as keys "the hub
sends no such key", and so does `owner_preferences` in the answer to
`PATCH …/members/{agent}`: §6.2 puts it in the member view where
`briefing` is, but the hub builds that answer without the view's
`details`, so the gap there is the hub's; a personal request from a project the reader is no
member of is seeded because only its notification carries
`project.member`; without that state the record reads as if the hub never
sent the key, and a fixture "fixed" to match would be wrong.
Lists the seed
leaves empty (attachments, aliases) are not compared. The seed's runner has
said hello, is attached and runs an agent in a project whose
`on_runner_revoke` is `stop`, as the fixture project's is, so a runner's
`capabilities` and `projects` and the `DELETE`'s `still_running` and
`on_runner_revoke` (with `stopped`) are compared with their items.
