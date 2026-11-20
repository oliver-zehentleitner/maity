# Plain text

## Names and short texts follow one rule, by Unicode category, kept in `plain_text.plain`; values stored before it are folded where they are written into text, not migrated

**Id:** 893c6bee-9785-4e29-ae44-c8e6c71947df
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-zadkerpebgd5 (one plain-text rule for names, notes, URLs and subjects), 2026-11-14; `plain_text.py` `NOT_PLAIN`, `plain`, `plain_line`, which tsk-kpaye5hmyz39 started for a bridge's purpose
**Revisit when:** Python's `unicodedata` gains Extended_Pictographic, an emoji sequence people use is refused in a name (one whose joiner stands after a symbol outside the emoji blocks, or one newer than the Python's Unicode data, whose code points are Cn there), or a field needs a character of the set (a name that must keep U+200D, a note that must keep a carriage return), or a migration touches the tables that hold these values anyway; also when names that look alike become a problem: the rule does not compare names, so a name of letters and spaces that reads as blank in some font, or one of Cyrillic letters that look Latin, passes; and when a ZWJ emoji in a display name shows split in a folded title (a notification title, the join page, the rules heading), which a name-aware fold would keep whole
**See:** mail.md#one-row-never-stops-the-outbox-a-mail-that-cannot-be-built-is-failed-before-it-is-admitted-and-rows-left-in-sending-need-no-migration — 34e5cd71-12cb-4484-b03c-2c4309665605 — as of 2026-11-14

One function in one module, `plain_text.py`, decides what plain text is (docs/api.md §1.7.1): no
character of Unicode category Cc, Cf, Cs, Co, Cn, Zl or Zp, except the line feed and the tab where a field takes several lines. Every
field the rule covers calls it: a project's name and every display name (`models.Name`,
`orgs.display_name_ok`, `registration_accounts.check_names`, `create_profile`, the operator's
`owner create`), an invitation's note, a card link's URL and label, a person's website and a
project's links (`person_links.website_problem`), a review's subject, and a human's preferences
(`preferences.check`); a bridge's purpose through `is_plain_line`, the same rule. The answer keeps each field's existing reason (`control_character`,
`not_a_url`, `format`, and `invalid` for a display name at registration and an organisation's), so a client that knew a field's reasons meets no new one there, except
the invitation note, whose character refusal now says `control_character` rather than
`invalid`.

The set is the one `routes/projects.py` `NOT_PLAIN` already used for a checklist line and
`routes/restricted.py` for a restricted text, Cs and Co included as there (a lone surrogate
cannot be written as UTF-8 and would fail later, in the database driver or a mail; a private-use
character has no meaning the reader can see). Cn (a code point this Python's Unicode data
does not assign, the noncharacters such as U+FFFF among them) came in at the review of the
card: it is what "a character nobody named" means taken one step further, and nothing showed
or tested a Cn character as plain. Its cost: a character Unicode assigns after the Python the
hub runs on, a new emoji too, is refused until the hub runs on a newer one. It replaces the narrower check of
tsk-dv8f620hjebf (`one_line`, Cc, Zl, Zp), which stays where it belongs: `mail/headers.py`
folds those characters out of a header, whatever was stored.

A value stored before the rule stays as it is. Where the hub writes a project's name into a
text or a Markdown line for agents (the join page's `_md`, the rules document's heading, the
summaries of the requests `foreign_agent`, `cross_owner` and `bridges` (a bridge's consent)
file, the commitment notice), and a display name into the text of a request or a mail (the
inviter in an invitation's request and mail, an organisation's name in the title of its
invitation's request; a project's name, a notification's title and a writer's display name in
a notification mail, subject and body), `plain_line` folds each run of refused characters into
one space first, before `subject_line`, which cleans only Cc, Zl and Zp;
the JSON answers carry the value unchanged. A notification's title is folded where it is built:
every title in `notifications/items.py` passes `_cut`, which folds the whole title (the
catalog's words hold no refused character, so only the stored parts change), and so the
notification list carries it folded too; the mail folds it again in the subject and the body,
for a title built elsewhere. The fold turns U+200D into a space, so an emoji sequence in a
display name shows as its parts in a title. The invitation's request and mail name the inviter
as "display name (@handle)", as the invitation page does: a display name alone can be anyone's.
The mail's subject keeps the display name alone, since the handle would push the project's name
toward the subject's cut and the body names it.

Names (`plain_name`, what `models.Name`, `display_name_ok`, `check_names`, `create_profile` and
`owner create` call) take one exception: U+200D only between two emoji characters and U+FE0F only
right after one (`takes_vs16`, below). An emoji character (`is_emoji`), the only one a joiner
stands between, is category So at U+1F000 or above (pictographs, the regional indicators), in
U+2600–U+27BF (miscellaneous symbols, dingbats) or in U+2B00–U+2BFF (miscellaneous symbols
and arrows, for U+2B50 and U+2B1B, common in names), or a skin-tone modifier (U+1F3FB–U+1F3FF,
category Sk). Python's `unicodedata` has no Extended_Pictographic property, and a dependency
(the `regex` package) for one property was not worth it. So alone, as the first version had
it, also holds symbols that are no emoji (U+00A9, the braille patterns, U+2800 among them,
which shows as nothing); the blocks narrow the joiner to where the emoji are. U+FE0F is looser
(`takes_vs16`): it asks for a character's emoji presentation, so it may follow an emoji
character, any So character in U+2000–U+2BFF but the braille patterns U+2800–U+28FF (U+2122,
U+231A), and U+00A9 and U+00AE, the symbols whose text form is the default. A joiner right after
such a pair, before an emoji character, passes too: the loop checks the character before the
selector with `takes_vs16`. A keycap (a digit, `#` or `*`, U+FE0F, U+20E3) passes as a whole:
U+FE0F follows such a base only with U+20E3 (category Me, which `NOT_PLAIN` does not hold)
right after it, and U+20E3 stands only after such a pair, so a bare U+20E3 is refused in a
name, a rule of names alone as the joiner's is. Braille is excluded by name because it is So inside that range and
U+2800 shows as nothing. Every other field, a bridge's purpose and notes included, refuses
U+200D as before.

A name that is not empty but holds only spaces (Zs) and the characters that show as nothing
though they are letters or symbols (the Hangul fillers U+115F, U+1160, U+3164, U+FFA0 and the
blank braille pattern U+2800, `plain_text.FILLERS`) is refused with the reason the field
already gives. Inside a name with something to read they pass: they are letters of a script.
The list is a list, not a category, because their categories (Lo, So) hold every letter.
Combining marks (Mn) are not bounded: a name can stack them, and U+034F or a variation selector
other than U+FE0F after a letter passes; they are how many scripts write.

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
