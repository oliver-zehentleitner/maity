# The landing page and the legal pages

## The landing page is checked against one table of section types, and a `PATCH` replaces the fields it names

**Id:** 3a452a0c-b2cc-4313-abba-b7e5d33cb05a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7; the implementation of tsk-2vv6h5jptvem, 2026-10-29; the contract text fixes the section types and limits, the way to check them is the implementer's
**Revisit when:** a section type is added or gets a required field (the table in `landing.SECTIONS` is the one place), or the dashboard's editor needs a partial `PATCH` of one language's page

`landing.SECTIONS` maps each section type to its fields as `(kind, limits, required)`; one recursive
check (`_field`, `_object`, `_list`) walks a page against it and records the first reason per field
path (`pages.de.sections.2.items.0.title`), so a new type is a table row, not a new function. A
section with an unknown type or field, a missing required field, a broken limit or a bad `href` is
`invalid` at its path; Markdown keeps the rules and the `line N` reason it already had. The setting
is stored as `pages` per language and `footer`, at most 256 KiB, and a `PATCH` replaces each top-level
field it names as a whole (`pages` too) and keeps the others: a client that sends the whole state gets
what it sent, and one that sends only `footer` does not lose the pages. `enabled` needs a page in
`default_language`. Migration 0090 carries the old one-body landing over as the `en` page (a `hero`
with the title and call to action, a `text` section with the Markdown).

**Reason:** the contract lists eleven types with limits; one table keeps the limits, the errors and
the rendering (a later change) reading the same description. Replacing a field as a whole is the
one rule an editor can predict, and the contract gives no merge for lists of sections.

**Rejected alternatives:**
- One validation function per section type: eleven near copies of the same loops, and a limit
  changed in one of them and not the other.
- A merge of `pages` by language or by section index: a client could not delete a section or
  language without a second call, and an index that moved would write into the wrong section.
- Dropping the old Markdown landing in the migration, as the alpha rule would allow: the operator's
  words are content, not code, and carrying them costs one function; the old fields themselves are gone.

## The legal pages keep every version, a page is served by a pointer, and unsetting moves only the pointer

**Id:** c321fdcc-6917-4363-97f2-4d3858ea33ec
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7.1 (versions kept, an unset page's earlier versions stay readable, 20 changes per page per day); the implementation of tsk-2vv6h5jptvem, 2026-10-29
**Revisit when:** a person's acceptance of a version is recorded (the terms at registration, §16.4), or the number of kept versions needs a limit beyond the daily one

`legal_version` holds every text a page ever had, keyed by the hub's time of the change in whole
seconds (the version), unique per page; `legal_page.current` says which version is served and is
null for a page that is not set; `instance_legal` is the setting's one row (default language, who
edited last). A `PATCH` appends a version and moves the pointer; `{"imprint": null}` moves the
pointer to null and deletes nothing, so a version a person accepted stays readable at its address.
Two changes inside one second get versions a second apart. The daily limit counts the versions a
page got in the last 24 hours, so unsetting costs nothing and a replacement costs one.

**Reason:** the contract says a person may have accepted a version, so a version is never edited or
removed; a pointer makes "set", "unset" and "replaced" one small write each and keeps the text
immutable. Counting the versions needs no counter row that could drift from them.

**Rejected alternatives:**
- A text column on the page that a `PATCH` overwrites, with the history in a log: the version a
  person accepted would be a copy that can differ from what the page said.
- A `deleted` flag on the version row for an unset page: the question "which version is served" would
  then need the newest row without a flag, and an unset page set again would reuse a flagged row.

## Migration 0090 makes a `hero` only when the old landing had both a title and a call to action

**Id:** 3a007583-49e3-484a-b2e4-0049619c01af
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the review of the landing sections change, 2026-10-29: `_carried` made a `hero` from a title alone or a call to action alone, which `landing.check` refuses with `cta_primary` or `title: required`
**Revisit when:** `hero` gets optional fields, or the migration has no stored landing left to carry
**See:** landing.md#the-landing-page-is-checked-against-one-table-of-section-types-and-a-patch-replaces-the-fields-it-names — 3a452a0c-b2cc-4313-abba-b7e5d33cb05a — as of 2026-10-29

The old schema allowed `title` and `cta` to be null; a `hero` needs both (§16.7). `_carried` now
builds the `hero` only when both are there. With a title alone the title is the page's own title and
no hero is made; with a call to action alone it is left out, since a `hero` or a `cta_band` without
a title would need an invented one; the Markdown becomes a `text` section either way. A migrated
page therefore passes the check of the setting, and the editor can read it and write it back
unchanged.

**Reason:** a stored state the setting itself would refuse breaks the round trip of the editor and
puts a section without a required field in front of the renderer.

**Rejected alternatives:**
- Filling the missing hero field with a placeholder: made-up words on the operator's public page.
- Loosening the check for migrated pages: two rules of validity for one page.

## The hub renders the landing page and the legal pages itself, as documents with a policy of their own; the legal pages carry no script

**Id:** 7b1e4c52-5a86-4f0e-9d3b-0c2a6e8f1d47
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7 ("The page", "Content security"), §16.7.1; the implementation of tsk-2vv6h5jptvem, 2026-10-29
**Revisit when:** a legal page needs a script or an image, or public pages (§16.9) arrive and `profiles`, `explore` and `activity` get something to show. The "no script, no image, one `<style>`" of the landing page held until landing V3 stage 1 (2026-10-30), which gave it the hub's own files, see the entry on its files below.

`render.py` turns a page into one HTML string: a fixed header, the enabled sections in order,
a fixed footer, a style that follows `prefers-color-scheme` (for the landing page the hub's own
stylesheet, below; for the legal pages one inline `<style>` element), and the
operator's words only ever as escaped text. Markdown goes through a small renderer that knows
exactly what the validator allows (headings, paragraphs, emphasis, lists, quotes, fenced code,
links whose target passes the same check again at render time). The documents answer with
`default-src 'none'; style-src 'unsafe-inline'` (the legal pages), which is why they have no image
and no logo file: the wordmark is text. The landing page's policy is wider since V3 stage 1 (below).
`/` shows the landing page to a visitor (no live `maity_session`; `has_live_session` reads, renews
nothing and never raises) while it is enabled, to anyone with `?as=public`, and the app shell
otherwise. The language is `?lang=`, else the best `Accept-Language` match among the languages
the page has, else the default language. The counters are computed at most every five minutes in
the process and shared by every visitor. A draft is stored in `preview_draft` (session-bound,
ten minutes, twenty per session), because the dashboard can only post with its CSRF token and
HTML it fetched would run under the dashboard's policy, not the page's: the second step is a
top-level `GET` that answers the page itself, in the language the `lang` query asks for or else the
draft's own default language (the browser's `Accept-Language` is not read), with the page's policy in
place of the API's. The `POST` answers the path under the API base, not an absolute address.

**Reason:** a crawler and a visitor with a script blocker read the same words; a policy that
forbids everything but the hub's own files leaves no way for an operator's text to run anything,
whatever it holds. The renderer repeats the validator's rules instead of trusting the stored
value, since a row written by an older version or by hand is still shown to the public.

**Rejected alternatives:**
- Serving the dashboard's shell at `/` and letting its script draw the landing page: a crawler
  would see nothing, and the page would need the dashboard's files and policy.
- A Markdown library: the validator already limits the language to a handful of constructs, and
  a general renderer would produce elements the policy and the validator never considered.
- Keeping the drafts in the process: the preview's `GET` may reach another replica than the
  `POST`; a row needs no sticky routing.
- Giving the landing page the dashboard's `default-src 'self'` and its stylesheet: it would allow
  the page to load files and make the policy depend on what the dashboard ships.

## The landing page's look is the hub's own files, served from the package under their digest; the page reads without them

**Id:** 7c22ec9b-0c71-4079-998e-a0900d395ac1
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.7 ("Progressive enhancement", "Content security", "Search engines"; contract #737) and the coordinator's decisions on card tsk-m6ew67r1w3hc, 2026-10-30 (the files come from the hub package, a stale digest answers `no-cache`, `img-src 'self'` without `data:`); the designer's board "Landing V3 – volle Fassung"
**See:** landing.md#the-hub-renders-the-landing-page-and-the-legal-pages-itself-as-documents-with-a-policy-of-their-own-the-legal-pages-carry-no-script — 7b1e4c52-5a86-4f0e-9d3b-0c2a6e8f1d47 — as of 2026-10-30
**Revisit when:** the hub serves a second public page of its own that wants the same files, an operator needs to restyle the page (today the look is code, the same for every instance), or the fonts' subset has to grow past Latin

The landing page loads `/assets/landing/landing.css`, `landing.js` (D's, at most 10 KiB, `defer`) and
nine `woff2` fonts (Space Grotesk 500/600/700, Inter 400/500/600/700, JetBrains Mono 400/500; the
Latin subset of the `@fontsource` packages, which carry the same OFL fonts, with the OFL texts beside
them). They live in the package (`hub/src/maity_hub/landing_assets/`) and `landing_files` answers them
with its own route, before the dashboard's `/assets` mount, so a hub without `MAITY_WEB_DIR` serves
the page complete. The page names each file with `?v=<digest>`, a 16-hex prefix of the file's SHA-256:
asked under its digest a file is `public, max-age=31536000, immutable`, asked under another or none it
answers the current file with `no-cache`, so a stale link repairs itself. The stylesheet holds
`{font:<file>}` where it names a font, and the hub fills in the font's own versioned URL when it first
reads the file, so the fonts are cached for good as well; the script is linked only when the file
exists. The hero's rings, the call-to-action band's loader and the logo are inline SVG
(`hero-rings.svg`, `band-loader.svg`, `mark.svg` beside the files, not served), coloured by the CSS
variables. Everything is text in the HTML: the demo's lines are `d1`… with the inbox item as `d5`
and the lines after the fourth following it. That is the designer's timeline (the question after the
fourth line, or after the last when there are fewer), which the coordinator takes into §16.7 (2026-10-30); building the timeline for the
inbox after any last line would mean generating it per number of lines. The steps are `s1`–`s3`, the
scales three columns in `.scales-grid`, the FAQ `<details>`, the counters `<span data-lp-count>`,
and the theme switch a `hidden` button in the page's language, so without the script the page
follows `prefers-color-scheme` and shows every end state. If the stylesheet cannot be read the page
carries the old inline style. The policy is `default-src 'none'; script-src 'self'; style-src 'self'
'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action
'none'; frame-ancestors 'none'` (`'unsafe-inline'` is for the inline SVG's `style` attributes),
on the page and on the preview. `robots.txt` allows `/assets/landing/` in both of its branches while
the page is enabled. The middleware keeps the cache the route chose for these files.

**Reason:** the designer's page needs a stylesheet, fonts and motion, and the contract keeps the
words in the HTML so that nothing is needed to read it. The rings, the loader and the pulses turn by
CSS alone, also without the script, and stop under `prefers-reduced-motion`; the script adds only the
demo's start (`.demo-on`), the counters and the theme (the coordinator takes this into §16.7, 2026-10-30, after the review of #739). Files in the package are the same for every
instance, need no dashboard directory and can be hashed when they are read; a digest in the URL
makes them cacheable for a year without a stale file ever being served for good.

**Rejected alternatives:**
- Serving the files from the dashboard's `web/` directory (`MAITY_WEB_DIR`): a hub without it would
  serve an unstyled page, and the hub could not know the digest of a file it does not own.
- A nonce or the hash of an inline script and style: the policy would change with every deploy and
  every page, and an operator's text could still be reached by a mistake in the template; a file of
  the hub's own is one origin the policy names once.
- Fonts from a CDN or from Google: a visitor's request would leave the hub, and `font-src 'self'`
  and the policy's whole point would go.
- `img-src 'self' data:` for the pictures: the pictures are inline SVG, which needs no image source;
  `data:` would let any markup an operator's text reached load an image.
- A `.lp-motion` class set by the script (D's first proposal): the designer's CSS already animates
  by itself and stops under `prefers-reduced-motion`, so the script only toggles `.demo-on`, the theme
  and the counters.

## The terms of a registration come from the legal pages only when neither the environment nor the admin gave any

**Id:** 94f2d0a6-1c3e-4b78-a5e9-6d7c0b8e3a21
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7.1 ("Terms at registration"), §16.4; the implementation of tsk-2vv6h5jptvem, 2026-10-29
**Revisit when:** an acceptance of a version is recorded per person, or the terms page is edited so often that the version a registration offered is gone before it completes

`registration.resolve` takes the environment's terms, else the admin's, else, when the legal
`terms` page is set, `{url: <public url>/terms, version: <the page's current version>}` with
`source: "legal_pages"`; unsetting the page returns to none. The version is the hub's RFC 3339 time
of the change, so a person accepts exactly the text they could read at that address, and the
earlier version stays readable (§16.7.1).

**Reason:** an operator who writes the terms in the hub should not have to type their address and
version a second time, and a value somebody set on purpose (the environment, the admin) must keep
winning over an inference.

**Rejected alternatives:**
- The legal pages winning over the admin's value: the admin would lose a setting they made on
  purpose without being told.
- Storing the derived terms in the registration setting at each change of the page: two stores
  that can differ, and an admin's explicit value could not be told apart from the copy.

Every caller of `registration.resolve` passes the public URL (`public_url` has no default): the
login page's `GET /auth/methods`, the registration's link page, `POST /registration`, the invitation
page and the admin's view must name the same terms, or the form says nothing about terms the link
page then requires.

**Rejected alternative:** a default of `""` for `public_url`. It silently dropped
`source: legal_pages` for `/auth/methods` (found in review of #635), the form showed no terms, and no
test noticed.

## Variants and campaigns are fields of the landing setting, served by the same renderer, and a link is rewritten only while they are set

**Id:** b8c0fea6-0888-4a32-9473-8524010b15be
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.7.2, §16.7, §16.11; the maintainer's decision of 2026-10-31 (A/B tests before the launch); `context/scope.md` (the entry that supersedes 02f126c2); the card tsk-tk10nnqdh8h1
**Revisit when:** a variant needs a header, footer or theme of its own, or the counts need more than the daily sums

`variants` (at most 5, by slug) and `campaigns` (at most 200, `{code, label}`) are two more JSON columns of `instance_landing` and two more fields of the setting that `landing.check` validates: a variant is `{pages}` checked by the very function that checks the main page's pages, so every rule of §16.7 holds under the path `variants.<slug>.pages…`, and the whole counts towards the 256 KiB cap. `GET /landing` answers the `FIELDS` of the page only (`ADMIN_FIELDS` is what the admin reads and writes): a campaign's code and label and a variant's pages are the admin's, and a visitor sees a variant only at its address. `/for/<slug>` is rendered by `render.landing_document(variant=…)` from the variant's pages; a language it lacks falls back to its own page in the default language, never the main page's, and the page says `noindex` and points its canonical at the root. A link to `/register` carries `v` and `c` (`render.carry_origin`, a rewrite of the finished page) only while `landing.configured` is true, together with `Cache-Control: private, max-age=60` instead of `public`; a code that is not in `campaigns` is treated as none and never echoed. An unknown or disabled variant answers the app shell, like any unknown path. The rewrite covers a link to `/register` as a path and as this hub's own address (an operator may write either as a button's target), and the visible language switch keeps the campaign so that a visitor who changes language does not lose it; the `alternate` links of the head are for search engines and carry nothing. `campaign_count` keeps "no campaign" as `""` because a primary key cannot hold `null`; the statistics (PR 2) give it as `null` and, in the CSV, empty.

**Reason:** a variant is the same kind of page as the main one with its own words, so one renderer and one validator keep the two from drifting; and a hub that does nothing about campaigns must stay exactly what §16.7 says, so everything new hangs on one predicate.

**Rejected alternatives:**
- A table of variants: five small documents that are always read and written together with the page, so a column is simpler and keeps the setting one row with one lock.
- A per-visitor choice of the variant: the contract has the link decide, no cookie, nothing that tells a visitor from another.
- Rewriting the links in the renderer's helpers (`_button`, `_link`): every new place that links to `/register` would have to know; one rewrite of the finished page cannot miss one.

## Campaign counts are daily sums with no visit behind them; the one thing kept with an account is its origin, until its first agent exchange or 30 days

**Id:** ec6a2993-1651-4d36-8bdd-b330335db233
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.7.2, §2.7.1, §2.9; the maintainer's decision of 2026-10-31 (A/B tests before the launch); the card tsk-tk10nnqdh8h1
**Revisit when:** a count is needed per hour or per anything but variant and campaign, or an activation must be told apart from a first exchange
**Verification:** corroborated

`campaigns.py` keeps one row per UTC day, variant and campaign in `campaign_count` (`views`, `registrations`, `activations`) and nothing about a visit: no address, session or account. A view is counted for a navigation by a browser to a page only (not for `HEAD`, a crawler, a fetch that is no navigation, the public view or a preview), and only while `landing.configured` is true. The origin of a registration travels in `pending_registration.origin` until the address is verified; the account then keeps it in `campaign_origin` (variant, campaign, day) for the one activation, which is counted at the first agent exchange (`routes/joins.py`) and ends the origin; an origin that nobody used ends after 30 days, the sums after 400. A variant or a campaign removed meanwhile is still counted under what the registration kept, a code that never existed is none, and when both are gone nothing is counted. The origin is the person's data: it is in the export (§2.9) while it exists and `account_deletion` deletes it with the account.

**Reason:** the question is which variant and which link bring registrations that turn into a working agent, and the answer needs sums, not people; the origin is the smallest thing that lets an activation be counted days after the visit, so it is bounded in time and removed with its use.

**Rejected alternatives:**
- Keeping the origin on the account for good: it would be a profile of where a person came from, long after the count needed it.
- Counting activations by looking at accounts later: that requires the permanent link between an account and its campaign.
- A cookie or a visitor id to count unique visitors: nothing in the contract tells one visitor from another, and the sums do not need it.

## A sum is raised by an increment in the database, the first of the day inserts the row inside a savepoint, and a lost insert race falls back to the increment

**Id:** 8be346aa-c8c0-4461-a790-b0f2375c683a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `hub/src/maity_hub/campaigns.py` (`count`); `docs/api.md` §16.7.2; the review of #882
**Verification:** corroborated
**Revisit when:** the hub keeps the sums somewhere else than a table, or one dialect gives an upsert all three can share

`campaigns.count` runs `UPDATE campaign_count SET views = views + n …` for the day, variant and campaign; when no row matched it inserts the row inside a savepoint, and when that insert loses to another request's (`IntegrityError`) it runs the same `UPDATE` again. Two visitors at once, also on different replicas of the hub, are both counted, because the addition happens in the database and no request holds a value it read.

**Reason:** the sums are the whole point of the feature, and the hub may run several copies against one database; a sum that two requests read and write back loses a visit whenever they overlap.

**Rejected alternatives:**
- Reading the row and writing the sum back: loses counts under concurrency.
- An upsert statement (`INSERT … ON CONFLICT`, `ON DUPLICATE KEY UPDATE`): one syntax per dialect, three code paths to keep right, for one statement that the update-then-insert fallback already makes correct on all three.

## Every counted view is a write in the request that served it, not a buffer flushed later

**Id:** bbc7f964-21e1-4153-910f-7a85203e37f5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `hub/src/maity_hub/routes/pages.py` (`_count_view`); `docs/api.md` §16.7.2; the review of #882
**Verification:** corroborated
**Revisit when:** the landing page takes enough traffic that the write shows in its latency, or the hub gets a place for a counter that every replica reads

A navigation to the landing page or a variant that counts (`campaigns.is_view`) increments `campaign_count` before the response is sent, only while variants or campaigns are set. There is no in-memory buffer and no background flush.

**Reason:** a buffer is lost when the process stops, differs between replicas and needs a flush the hub has no place for; one small write per view is exact, and the page is cached only privately (`private, max-age=60`) while counting, so a browser asks the hub at most once a minute.

**Rejected alternatives:**
- A buffer per process, flushed on a timer: the counts of a stopped process are lost and the statistics would be approximate in a way no one could bound.
- Counting from the request log: the log is not a store the hub reads, and a count from it would tie the statistics to what the log happens to keep.

## The header's links come from `nav_label`, the footer's columns from fields the page already has, and the hero's online numbers from the shared stats

**Id:** c66b9197-107c-46c0-a873-9618368121b0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7 (#905); the card tsk-7en17gygg3gf and its notes from the coordinator, 2026-10-31 (the designer's review of the live page against the board "Landing V3 – volle Fassung", Oliver's decision to make the page look like it)
**See:** landing.md#the-landing-pages-look-is-the-hubs-own-files-served-from-the-package-under-their-digest-the-page-reads-without-them — 7c22ec9b-0c71-4079-998e-a0900d395ac1 — as of 2026-10-31
**Revisit when:** an operator needs a footer the columns cannot hold (a link that belongs to no section and no list), or the page offers more than four header links

Any section may carry a `nav_label` (trimmed, 1–24 characters); the header links the enabled sections that have one and
draw something, in order, at most four (a fifth enabled one is `too_many`; a disabled one does not count). A section that
draws nothing in this version (`activity`, `collab`, `profiles` and `explore`) is no link even with a label. A title is never a
link text. The footer's columns are made of what the page has: Platform (the header's links, sign-in, registration), Open source
(the `links` of the `opensource` sections), Legal (the legal pages that are set) and Follow (`footer.social`), then the operator's
line and the language switch; a column with no link is left out. The hero's online numbers come from the shared stats
(`people_online`, `agents_online`, only the ones an enabled `stats` section names), beside a note that is one plain line; a counter
below the floor is left out, never shown as "< 5".

The hero's online numbers follow the rule of `GET /landing`, applied to the page that is drawn: only a counter that an enabled `stats`
section of that page names is shown, because the page is handed every counter and the renderer filters (`landing_document`). It is
per page, not across languages, so a variant (which `GET /landing` does not publish) obeys it too and a language that does not name
a counter shows none of it. Rejected: showing every online counter as soon as any `stats` section is on, which would publish a counter
the operator took off. In a test the naming rule can only be seen with at least five online, since below the floor the counter is
left out anyway.

The board's last details are drawn by the same renderer: an online counter in the strip has the live dot before its number, the hero line
puts the online numbers before the note, a `github.com` link is left out of the Follow column when the Open source column has one (the
host is compared, not the whole URL), and the scales' two-column container is `.scales-body` with the panels left and the rings in
`.scales-art` right, the tab bar a sibling placed before it by `landing.js`. The route loads the stats only when a main page's enabled
`stats` section names a counter (`routes/pages.py`, `landing_stats.named` reads `pages`, not `variants`), so a variant with a `stats`
section and no main page that has one shows neither the strip nor the hero numbers; kept as it is, since `GET /landing` publishes by the
same rule.

**Reason:** the live header wrapped to two lines because the five section titles were its link texts, so a short label of its own,
chosen by the operator, is the only way to keep one line without a fixed list in the code. The footer needs no field of its own
because every link it shows already exists elsewhere on the page, so a new contract field would only repeat them. The numbers come
from the one set of stats that is computed every five minutes and shared, so the hero shows no number the page's own counters would
not publish.

**Rejected alternatives:**
- A fixed list of header links in the template (How it works · Open source · FAQ): the operator's page would show links to
  sections it does not have, and in no other language.
- Cutting the section titles to fit: a title is text for the section, and its length is the operator's.
- A `footer.columns` field: another contract field for links the page already holds.
- A "< 5" in place of a counter below the floor: it stands next to a larger total and invites reading who is online.

## A page's languages are listed with the default first and the rest alphabetically

**Id:** 59f1acda-b6e4-4a93-a2a6-9503ab1b2689
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7; the `hub-postgresql` CI job on #909, 2026-10-31, and the reviews of the fix (n3yv, c47w); the card tsk-hztv5d16x9g1
**See:** persistence.md#nothing-is-derived-from-the-order-of-the-keys-of-a-json-object-read-back-from-the-database — 04ed9b8c-ce31-4c97-a761-3c4278cf9039 — as of 2026-10-31
**Revisit when:** an operator wants to say in what order the languages are offered (the setting would then need a list, not only the `pages` object)

`render.ordered_languages(pages, default)` is the one place that puts the languages of a setting in order: the default language first,
the others alphabetically. The language bar of the footer, the `hreflang` links, the page a missing language falls back to and the
choice among the offered languages when nothing matches (`choose_language`, last resort) all take it, so they are the same on every
database.

**Reason:** the setting keeps its pages in an object whose key order the database does not keep (PostgreSQL's `jsonb` sorts it), so
without a rule the footer showed the languages in a different order on the production database than in the tests; a rule that does
not depend on how the object was saved is the same everywhere.

**Rejected alternatives:**
- The order in which the admin created the languages: it cannot be stored in a `jsonb` object without carrying a list of its own,
  and the contract has no field for one.
- Fixing the test to expect the database's order: the page would still differ between databases, and an operator could not predict it.

## The agents of a `works_with` section are a list in the hub's code, with their logos beside it

**Id:** fd53bea7-4f81-4b2c-99f7-1d3803f585b0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** `docs/api.md` §16.7; the maintainer's decision of 2026-10-31 on the card tsk-6g1jxzk1xh1b (the set of agents, the designer's file with the marks' origins)
**See:** landing.md#the-landing-pages-look-is-the-hubs-own-files-served-from-the-package-under-their-digest-the-page-reads-without-them — 7c22ec9b-0c71-4079-998e-a0900d395ac1 — as of 2026-10-31
**Revisit when:** an operator needs an agent the list does not have, or an owner of a mark asks for its removal

`landing.AGENTS` maps a slug to the name shown; `landing_assets/agents/<slug>.svg` is its logo, served under
`/assets/landing/agents/` like the stylesheet. The page names slugs only: an unknown one is `unknown_agent`, a repeated one
`duplicate`, and the JSON cannot carry a logo, an address or a name. The logos are third-party marks stored as received, so the
folder has a `NOTICE` (origin, terms, how to ask for removal) that `LICENSE` and the README point to and that ships with the files
in the package. The band recolors the files with a CSS mask, so the files stay unedited and one color serves both themes; it
needs no script.

**Reason:** `img-src 'self'` and the rule that the page's JSON never becomes markup or a request leave no place for a logo
address in the page; a fixed list also keeps the marks' terms in one reviewable place.

**Rejected alternatives:**
- A logo or URL field per item: it would open the page to any image and put third-party marks under the operator's own
  responsibility with no record of their terms.
- Redrawing or recoloring the files: the designer's source keeps them byte for byte so a removal or replacement is file by file.
- The list in the stylesheet or script: the band would then depend on the script, and validation could not know the names.
