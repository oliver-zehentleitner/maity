# Plain text

## Names and short texts follow one rule, by Unicode category, kept in `plain_text.plain`; values stored before it are folded where they are written into text, not migrated

**Id:** 893c6bee-9785-4e29-ae44-c8e6c71947df
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-zadkerpebgd5 (one plain-text rule for names, notes, URLs and subjects), 2026-11-14; `plain_text.py` `NOT_PLAIN`, `plain`, `plain_line`, which tsk-kpaye5hmyz39 started for a bridge's purpose
**Revisit when:** Python's `unicodedata` gains Extended_Pictographic, an emoji sequence people use is refused in a name, or a field needs a character of the set (a name that must keep U+200D, a note that must keep a carriage return), or a migration touches the tables that hold these values anyway
**See:** mail.md#one-row-never-stops-the-outbox-a-mail-that-cannot-be-built-is-failed-before-it-is-admitted-and-rows-left-in-sending-need-no-migration — 34e5cd71-12cb-4484-b03c-2c4309665605 — as of 2026-11-14

One function in one module, `plain_text.py`, decides what plain text is (docs/api.md §1.7.1): no
character of Unicode category Cc, Cf, Cs, Co, Zl or Zp, except the line feed and the tab where a field takes several lines. Every
field the rule covers calls it: a project's name and every display name (`models.Name`,
`orgs.display_name_ok`, `registration_accounts.check_names`, `create_profile`, the operator's
`owner create`), an invitation's note, a card link's URL and label, a person's website and a
project's links (`person_links.website_problem`), a review's subject, and a human's preferences
(`preferences.check`); a bridge's purpose through `is_plain_line`, the same rule. The answer keeps each field's existing reason (`control_character`,
`not_a_url`, `format`), so a client that knew a field's reasons meets no new one there, except
the invitation note, whose character refusal now says `control_character` rather than
`invalid`.

The set is the one `routes/projects.py` `NOT_PLAIN` already used for a checklist line and
`routes/restricted.py` for a restricted text, Cs and Co included as there (a lone surrogate
cannot be written as UTF-8 and would fail later, in the database driver or a mail; a private-use
character has no meaning the reader can see). It replaces the narrower check of
tsk-dv8f620hjebf (`one_line`, Cc, Zl, Zp), which stays where it belongs: `mail/headers.py`
folds those characters out of a header, whatever was stored.

A value stored before the rule stays as it is. Where the hub writes a project's name into a
text or a Markdown line for agents (the join page's `_md`, the rules document's heading, the
summaries of the requests `foreign_agent` and `cross_owner` file, the commitment notice),
`plain_line` folds each run of refused characters into one space first; the JSON answers carry
the value unchanged.

Names (`plain_name`, what `models.Name`, `display_name_ok`, `check_names`, `create_profile` and
`owner create` call) take one exception: U+200D only between two emoji characters and U+FE0F only
right after one. An emoji character is category So or a skin-tone modifier (U+1F3FB–U+1F3FF,
category Sk). Python's `unicodedata` has no Extended_Pictographic property, and a dependency (the
`regex` package) for one property was not worth it; So covers pictographs, dingbats and the
regional indicators, and a joiner between two of them hides nothing a reader would mistake for
letters. Every other field, a bridge's purpose and notes included, refuses U+200D as before.

**Reason:** a check per field had drifted: some refused only ASCII controls, some also DEL, one
every format character, none the C1 range or the separators everywhere. One function in the
module of its own, which `models` and the bridge code import alike, gives every field the same answer and one place to
change it. Category beats a list: a format character nobody named (U+061C, U+180E, the tag
block) is refused without a code change. Folding at the few places that build text from a stored
name protects every reader of those texts at once, also against a value that came in by a path
the checks do not see (an import, the database by hand); a migration would only clean what is
stored today.

**Rejected alternatives:**
- A migration that cleans the stored values: it needs a migration slot and a rewrite of six
  tables on SQLite, PostgreSQL and MariaDB, changes what people typed without telling them, and
  still leaves the output side open for a value that arrives later by another path. Before the
  launch the instance holds few such values, and each owner can rename.
- Cleaning on every read (each view folds the value): every view would need it, and the API
  would answer something other than what is stored; only the text the hub builds needs it.
- Refusing all of Cf in names too, U+200D included: it would refuse emoji sequences such as
  the technologist sequence U+1F469 U+200D U+1F4BB that people put in display names. The lead's decision (2026-11-14) is the narrow
  exception below.
- A new reason such as `format_character`: clients would need a new branch for what is one
  refusal to the person typing.
