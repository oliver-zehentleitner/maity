# Why

## A Keep the Why notice about an agent leads to its project's Members, or to one's agents on the account

**Id:** be999be7-325a-4fcf-954a-2bdadb6e6f84
**Type:** decision
**Status:** superseded
**Superseded by:** none — the notification kind `keep_the_why` was removed on 2026-10-26 (docs/api.md §18.2, "No longer notifications"), so the dashboard has no such item to link anywhere; an unconfirmed commitment now reaches the owner as a request in the inbox (§6.23), linked like every request
**Evidence:** confirmed
**Source:** docs/api.md §6.23 and §18.2; the coordinator's ruling of 2026-10-25 on the item's target and the interim place (tsk-bq6q65910g13); the dashboard's implementation, 2026-10-26
**Revisit when:** the dashboard gets a page of one's agents outside any project

The `keep_the_why` item names the agent as `target: {type: "member"}`.
Where the owner is a member of the project it opens
`#/p/<slug>/team/<agent id>`; where not, `#/account/picture/<agent
id>`, the list of one's agents on the account, with that agent marked
and focused.

**Reason:** the owner of an agent need not be a member of the project the
agent works in, and cannot open that project; the account's list is the
one place the dashboard shows all of one's agents.

**Rejected alternative:** the cross-project inbox (`#/all`), where other
items of a project one cannot open go: it says nothing about the agent.
A new page of one's agents: the right place, but beyond this change; the
link moves there once it exists.

## The project's Why view mounts the Keep the Why views, loaded on the first visit; their own words stay English for now

**Id:** 9e70b2ab-5fbf-44ad-9d4e-7e1b54319519
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** tsk-9kns2as984et (KTW M3), 2026-11-03: the proposal on the card and the lead's ruling on its two open points (the library's language, loading)
**See:** stack.md#the-keep-the-why-views-are-vendored-from-the-pinned-pypi-wheel-by-their-manifest-and-hashes-not-taken-as-a-package-dependency — f3b6fe34-f86e-490c-afe6-f03ee3263ab3 — as of 2026-11-03
**Revisit when:** the Keep the Why library takes its UI words from its host (a words hook), or a second view needs the library

The project's Why tab is Keep the Why's own dashboard views, mounted by `js/ktw-host.js` from the vendored library: the overview, graph, timeline, thoughts, family, topics, entries and search, at paths below `/<owner>/<slug>/why`. The library reads through a provider over the hub's §11.5 reads, moves through the dashboard's paths (`js/route.js`), keeps its settings in the browser and takes Maity's colours through its `--ktw-*` tokens. Its scripts and stylesheet are loaded on the first visit to Why, in the manifest's order (checked by `make check`), and stay for the page's life. Its own UI words are English and the mounts carry `translate="no"`: an interim step until the library takes words from its host; entry text is the repository's data either way. The digest view the tab showed before (the hub's §11.3 summary per member) remains on All projects → Why. What the old view did for a failed read stays: when the hub cannot read the export, its last good read is shown with the reason, and Read again drops what the page holds and reads anew. A link from data is used only when plain https, as for every link from data (rendering.md), in two places: the export's link fields (the project's and the config's canonical, dashboard-state, a git remote and the repository it forks, a See or superseded_by into another repository) are checked before the library sees them, and every `href` the library writes into the mounts, entry text included, is checked again as `dom.h` checks Maity's own (a path of the dashboard or plain https); a `ref` place reads nothing for a repository in the address that is not plain https. Since 0.11.44 the library writes a route's `centre` as `centre/public/<canonical>/<root>/<place>`; the host's router drops an empty path segment, so it never reads a repository's root back from that form with certainty. An entry at another repository of the family is therefore written by the host as its own place `at/<uuid>/<canonical>[/<root>]`, which reads that repository's export (at that root) through the family and draws the entry with the library's pages over a scene of that export; `routeOf` also takes the library's `centre/public/…` form when a link arrives from elsewhere (a segment after the canonical is the root unless it names a place of the library's grammar, so a root named like a place, `graph` say, reads as that place: a known limit of links from elsewhere, never of `at/`), and any other place at another repository is the family page. A `ref` place the library resolves goes on to that place, replacing the ref in the history. The repository in the address must be plain https and the root a relative directory, or nothing is read.

Since keep-the-why-dashboard 0.11.44 the library takes contrast tokens: text on its accent is `--ktw-on-accent` over `--ktw-accent-fill`, and accent-coloured text (links, counts, the type pill) is `--ktw-accent-text`. `css/app.css` maps the first pair to Maity's own `--accent-text` on `--accent` (5.32 to 1 light, 6.0 to 1 dark) and drops the eight overrides that wrote `--accent-text` over the library's literal `#fff`; they were a workaround until such a token existed. `--ktw-accent-text` is not `--accent` itself but `--accent` a fifth of the way to `--text`, as `--ktw-warn` already is: plain `--accent` is 4.11 to 1 light and 3.98 to 1 dark on the type pill's 18% accent tint, under AA, while the mix is 4.84 to 1 at least on `--bg`, `--surface` and that tint over either, in both themes. Mapping `--ktw-accent-text` to Maity's `--accent-text` was rejected: in Maity that name is the text *on* the accent (white in light, near-black in dark), not accent-coloured text, so links would turn white or black. `--ktw-status-active-text` is `--ok`, as `--ktw-status-active` is. Since 0.11.45 each of the library's state colours has a `-text` twin for its words (`--ktw-ok-text`, `--ktw-warn-text`, `--ktw-status-open-text` and eight more); the colour keeps drawing borders, dots and the graph. Upstream draws those words on the pills' solid `--ktw-surface2`, and on the surface and the page, never on a tint, so `css/app.css` maps them to Maity's text-on-plain-ground values: the state colour itself where it passes there (`--ok`, `--bad`, `--muted`), else the colour a fifth of the way to `--text` (`--ktw-warn`, `--ktw-accent-text`, `--ktw-accent2`). Plain `--accent` was rejected for the open and info text: it is 4.53 to 1 on dark `--surface-2`, too close to the line. The lowest pair is `--ok` on light `--surface-2`, 5.00 to 1. `--ktw-fg3-line`, the library's faint lines and marks, is `--muted` like `--ktw-fg3`, so nothing shifts; `--seat` was rejected, at 2.5 to 1 it is under the 3 to 1 a mark needs. Likewise, controls the library labels only by `title` (the timeline's playhead and speed) get an `aria-label` from that title in the host, where `sweep` holds its links, and a later title refreshes the name the host set, while a name the page sets afterwards is kept when it differs from the host's (one equal to it cannot be told from the host's and follows the title); dropping axe's `label-title-only` rule for the mounts was rejected, as it would hide the next unlabelled control too.

**Known limits:** what the page has read of a project stays for the page's life, per project and per signed-in reader; a newer export shows after Read again or a reload. The library's own words are English until it takes them from its host. A link in the library's `centre/public/…` form to a repository whose root is named like a place of the library's grammar reads as that place.

**Reason:** one update of Keep the Why reaches Maity unchanged, so the project's decision record looks and behaves as in its own dashboard; Maity adds only the host (provider, paths, settings, colours). Loading on the first visit keeps about 350 KB of scripts off every other page. Marking the library's words `translate="no"` keeps the pseudo-locale check strict for Maity's own words without pretending Maity translates text it does not hold.

**Rejected alternatives:** the library in `index.html` for every page: its weight on pages that never show it. Its ~200 words copied into Maity's catalog: a second copy that drifts from the library's on every release; the words hook in Keep the Why is the lasting answer. Keeping the digest view and the library side by side in the tab: two answers to one question, the digest the poorer one. Checking only the export's fields, or only what the library writes: the fields keep a bad link from shaping what the library builds from it, the check of the mounts covers links in entry text and any field a later library adds. An elsewhere view of Maity's own for a `centre`: a second rendering of an entry the library's pages already draw. A centred entry as its `ref` place: the library's `ref` resolves the entry and goes to it at that centre, which was the same address again, so the page never left "Looking for …"; and a child root had no place in it.
