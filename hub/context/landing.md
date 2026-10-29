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

## The hub renders the landing page and the legal pages itself, as documents with no script, no image and a policy of their own

**Id:** 7b1e4c52-5a86-4f0e-9d3b-0c2a6e8f1d47
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** `docs/api.md` §16.7 ("The page", "Content security"), §16.7.1; the implementation of tsk-2vv6h5jptvem, 2026-10-29
**Revisit when:** a section needs a script or an image (the policy and the renderer change together), or public pages (§16.9) arrive and `profiles`, `explore` and `activity` get something to show

`render.py` turns a page into one HTML string: a fixed header, the enabled sections in order,
a fixed footer, one inline `<style>` element that follows `prefers-color-scheme`, and the
operator's words only ever as escaped text. Markdown goes through a small renderer that knows
exactly what the validator allows (headings, paragraphs, emphasis, lists, quotes, fenced code,
links whose target passes the same check again at render time). The documents answer with
`default-src 'none'; style-src 'unsafe-inline'` (the landing page adds `base-uri`, `form-action`
and `frame-ancestors`), which is why there is no image and no logo file: the wordmark is text.
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
forbids everything but one style element leaves no way for an operator's text to run anything,
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
