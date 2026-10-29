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
