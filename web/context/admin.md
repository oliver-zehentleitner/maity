# Administration

## Statistics sum counts of things over the window and show people by their busiest day

**Id:** 39d109d7-026a-4d53-b7c2-5fda6ff51b77
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the cards tsk-73gz17sbq1k4 and tsk-h8805v7phn9b and docs/api.md §16.6 (per-day series, counts only, no chart library beyond the dashboard's); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub answers distinct active people per window, or the designer reworks the tiles

Each day series is one row: the window's figure, today's value and a
small line of the days. For registrations, new instances, cards and
reviews the figure is the sum of the days; for humans and agent
instances active it is the highest day ("up to N a day"). The days are
also a folded table, which is what a screen reader reads; the lines are
inline SVG drawn by the page.
Days the hub cannot know (reviews before it kept card history) are a dashed
line at the foot of the row, so every row spans the same width without
drawing an unknown day as a solid zero.

**Reason:** the hub counts a person active once per day, so adding the
days would count the same person thirty times and look like growth that
is not there; a distinct count per window is not in the answer, and the
page invents no number. One line per series keeps every chart to one
scale and one colour, so none needs a legend. Every row spans the same
width so the rows can be read against each other by day, and an unknown
number is never shown as a 0.

**Rejected alternative:** a sum for every series: wrong for people.
A gap for the unknown days: the line starts in the middle of its row. A
solid line at zero: it invents a number.
One chart with all series: eight scales in one axis, and colours that
would need a legend. A chart library: the contract and the CSP keep the
page to its own code.

## Abuse reports are a section of /admin: the snapshot as text, each action said before it is sent, a suspension asked first

**Id:** f4e5de2b-d329-444e-b98f-1ea8888b147a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's launch card tsk-d4ppa9jsj0d7 (the hub has the routes, the dashboard had no screen), 2026-10-30; docs/api.md §16.8 (the snapshot is the one content an instance admin reads; text untrusted; the four actions; a suspension lifted only by the operator)
**Revisit when:** reports get a target of their own for organisations, or an admin may lift a suspension from the dashboard

The instance admin's **Reports** section (`js/admin-reports.js`) lists
the reports as the hub orders them (open first, newest first), filtered
by status and type; it opens on the open ones, though the hub's default
is all, because the open ones are the admin's work. One opened shows the reporter's text and the
snapshot, every field as plain text in `pre` or a definition list,
never as markup or a link. The action is chosen from the four with the
effect of each said under the choice. **Suspend** asks for a
confirmation naming the target. A resolved report can be resolved
again to replace its action, and **Dismiss** then lifts its hold.

**Reason:** the snapshot is untrusted content that someone chose to
report, often because it is hostile (prompt injection, spam); shown as
text, nothing in it acts. A suspension ends every session and
credential of an account at once and only the operator lifts it, so it
is the one action asked twice.

**Rejected alternative:** opening the reported target in its project:
§16.8 gives the admin no read of the project, only the copy. Confirming
every action: dismiss and hide are undone by resolving again, and a
dialog for each would teach clicking through.

The fixture hub (`js/api.js`) mirrors `/admin/reports`; the e2e step
`reports_admin_step` checks the shapes against the real hub, because
the fixture's default status, its `closed_at` on a second resolve and
the snapshot missing from its `resolve` answer had drifted once (review
of #778).

## The limits per person are chosen as a number, no limit where the contract has it, or the default, the environment's shown locked

**Id:** 28adb478-d5fa-450b-9bbd-e985d93405c4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the coordinator's launch card tsk-d4ppa9jsj0d7 (the hub had `GET`/`PATCH /admin/settings/limits`, the dashboard no screen), 2026-10-30; docs/api.md §16.5 (the values, `unlimited`, `null` restores the default; `max_aliases` 1–8 without `unlimited`), §16.2 (sources), §2.8.4 (step-up); the dashboard's implementation; card tsk-1zng488dbprp (`max_aliases`), 2026-11-06
**Revisit when:** plans set the limits per plan (§2.7, part two), or the hub adds a limit

The **Limits** section (`js/admin-limits.js`) shows each value with a
choice of how it is set — a number, no limit, or the default — the
number field only for the first, the value's source in words and the
people at or over it. A bounded value (today `max_aliases`, 1–8)
offers only a number or the default, because the contract has no
"no limit" for it and the hub refuses `unlimited`. A value from the environment is shown, its
controls disabled. Only changed values are sent: a number, `unlimited`,
or `null` for the default; the call goes through `M.stepUp.run`, so a
missing second factor or password is asked where it stands.

**Reason:** the contract gives three different meanings — a number,
"no limit" stored by the admin, and the default restored by `null` —
and one number field cannot say the last two apart; an empty field read
as the default would be guessing.

**Rejected alternative:** a single number field with "0 means no
limit": the hub refuses 0 (`invalid`), and the default would still need
a gesture of its own.

A refusal whose `fields` name no field shown here is said in the status
line, because a display at the fields only would swallow it (merge of
#782 into #778).

## The instance admin area shows one section at a time

**Id:** 4c499cf2-cd9d-4ce1-be8d-639aa32306b6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the designer's pass part 3 on #371 (tsk-w2xnkrwf147m), 2026-10-27: the admin page was one scroll of about 5,000 px (Statistics, Users, Mail settings, Landing page, Instance information); docs/api.md §18.2 (a `registration_pending` item links to Admin → Registration; until 2026-11-04 a `report_open` item to the report in Admin → Reports, since then a report's request in the inbox, §16.8) and the review of #778, 2026-10-31
**Revisit when:** a section other than Registration and Reports needs a link of its own, or the area grows past one row of buttons

`/admin` reads every section as before, then shows one: a row of
buttons at the top names them (`aria-pressed` on the shown one), and the
page opens on the first, Statistics. A section whose read fails says so
in its place (until 2026-10-30 a section the hub did not serve left the
row, e1699490). The others stay
in the page, hidden, so a form half filled in keeps what was typed.
The two sections a notification or a request leads into have an
address: `/admin/registration`, and `/admin/reports/<id>`, which opens
that report as well (the target of a report's request, entry
f50ed8ee-5948-43c8-817a-d1b008bf1f5a). The page is the same, opened on that section; the
section is found by the hub path it reads, not by its label, which is
translated.

**Reason:** the admin comes for one thing at a time; five long sections
under each other hid all but the first below the fold.

**Rejected alternative:** a sticky list of anchors over the whole page,
the designer's other option: the scroll stays 5,000 px, only the jump is
shorter. A route for every section (`/admin/users`): only the two
sections a notification or a request names need a link. The older Users page at `/admin/users` was removed
before launch with the other compatibility routes, so that address is
now no view at all.

## Registration in the admin area: missing beside the fields, a block lifted by its typed address

**Id:** 9e0abafa-9fb3-41ba-b9b0-648e7e9523c0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.4, §2.7, §2.7.5; the card tsk-64tktcnndzk3 (the maintainer found no registration setting, 2026-10-29); the dashboard's implementation, 2026-10-29
**Revisit when:** the hub lists blocked addresses, or approval gets mails of its own (#280)

The Registration section says first what the hub does now
(`effective_mode`) and, beside the fields, in words what keeps
registration from working (`missing`: mail, an empty allowlist). A value
the environment sets, or terms that come from the legal pages, is shown
with its source and not offered. Lifting a block takes a typed address,
since the hub has `DELETE /admin/registrations/blocks/{address}` but no
list of blocks.

**Reason:** a mode that is set but not in effect (no mail) looks like
open registration that does not work; saying the gap where the admin is
looking avoids searching for it. A field the hub would refuse
(`set_by_environment`) is no choice. Without a list, a typed address is
the only way to the endpoint.

**Rejected alternative:** the mode alone, with the hub's refusal on
saving: the admin would learn of missing mail only by trying. A list of
blocked addresses kept by the dashboard: it would show only what this
browser lifted or saw rejected, not what the hub holds.

## A decision on a waiting account refreshes the counts, not the registration form

**Id:** 3f98cded-98a8-45d6-9cff-b92b3f531275
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the review of #660 (P3), web/js/admin-registration.js, docs/api.md §16.4, 2026-10-29
**See:** views.md — 9e0abafa-9fb3-41ba-b9b0-648e7e9523c0 — as of 2026-10-29
**Revisit when:** the settings form and the pending list move to separate views, or the hub sends the counts with the decision's answer

After Approve or Reject the Registration section reads
`GET /admin/settings/registration` again for `pending` and the hour's
counts, and redraws only those lines with the mode in effect and what is
missing; the form under them keeps what the admin has typed and not
saved.

**Reason:** the form and the list share one section; redrawing the form
from the hub's answer threw away unsaved edits without a word, while
the only thing a decision changes there is the counts.

**Rejected alternative:** redrawing the whole section after a decision,
as first built: unsaved edits lost. Redrawing the form only when it is
unchanged: it needs a comparison of every field with the hub's values
for nothing the counts alone do not already give.

## The landing page is imported and exported as JSON in its editor; an import is checked by the preview call and saved only by Save

**Id:** c174a492-2691-4887-9507-e1ba2e805a1f
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-36d575f5yybz (the maintainer, 2026-10-30: load the prepared landing V3 with one click; paste or file, the body of PATCH …/landing or one page; the hub's refusals per field; nothing saved before the admin confirms; Export the draft); how it is checked is the implementer's
**Revisit when:** the hub offers a check of a landing draft of its own, or imports grow to the legal pages

Under the landing editor, **Import or export JSON**: a field and a file
choice. **Export the draft** writes the draft as the hub takes it
(enabled, default language, pages, footer) into the field; **Copy**
copies it. **Load into the editor** reads either that body or one
language's page (title, description, sections), asks before it
replaces the whole draft or the page shown, draws the editor from it,
and sends it to `POST …/landing/preview`, the hub's own check, which
stores a draft for ten minutes and saves nothing. Its refusals are
said at their fields as a save's are; **Save** stays the only call that
saves, so the confirmation that counts is the admin's Save after
looking the import over. A field the imported body leaves out keeps what
the editor has, as a `PATCH` keeps the stored one: the prepared V3 file
has no footer, and an empty operator line is one the hub refuses
(`footer.operator` is 1 to 120 characters or none), so the editor sends
none instead of an empty one. The hub checks an import before the
editor is drawn from it; a body whose pages, sections or lists are of
the wrong kind leaves the draft as it was. That kind check covers every
value the editor binds to an object, not only lists: a button, a group
and each footer link must be an object, or absent where optional, or the
editor would break after the draft was replaced. A section's type is
looked up among the editor's own types only (`Object.hasOwn`), so a
`constructor` or `__proto__` in an import is drawn as an unknown section,
never taken for something every object inherits. Save asks for the
step-up (§2.8.4) the hub requires for this call.

**Reason:** the preview call already validates a draft exactly as a
save does, so the import reuses it instead of a second check in the
page that could drift from the hub's. Drawing the import into the
editor before anything is stored lets the admin read and fix it there.

**Rejected alternative:** saving on import, with a confirmation: one
click from a file to visitors, without the editor in between. A check
of the JSON in the page: a copy of the hub's rules that ages with each
new section type. Drawing inside try/catch and restoring the draft
afterwards: it would hide real drawing bugs and leave a half-built
editor behind.

## Landing variants are edited one at a time in the landing editor; campaigns sit beside the privacy hint, their counts in Statistics

**Id:** 43d9837f-64fd-44d8-9527-1e590092ad38
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-ets3x0c4ethg with the maintainer's request for A/B testing before the launch, 2026-10-31; docs/api.md §16.7.2 (contract #823)
**See:** https://github.com/oliver-zehentleitner/maity — b9dc57f9-7581-47ef-acc8-00b679f7aa1e — as of 2026-10-31
**Revisit when:** the hub serves more than five variants, or a variant gets a header or footer of its own

The landing editor edits one page at a time: the main page or one
variant, picked in a row of buttons above the languages, with the same
page editor. Only the path prefix of the hub's refusals differs
(`variants.<slug>.pages`). A variant starts with an empty page in the
default language, the one the hub requires. A language it lacks shows
its own default page, which the editor says. **Campaigns** are a list of
code and label next to the privacy hint the contract asks the dashboard
to show. Both travel with the setting in one `PATCH`, in the preview
and in the JSON import and export. **Statistics** shows the campaign
counts for the same window as the instance's figures and links the
hub's CSV. The fixture hub serves no file, so there is no link there.
The registration page sends `v` and `c` from its address as `origin`,
dropping a malformed part; the hub decides the rest.

**Reason:** a variant is a page like the main one, so the editor the
admin already knows serves it. Two editors would drift. The counts
belong with the other counts. The CSV is the hub's own, so the columns
cannot differ from what the contract names.

**Rejected alternatives:**
- A separate Variants section in the admin area: the same page editor
  twice, and header and footer, which variants share, would look
  editable twice.
- Building the CSV in the browser from the JSON: it works in fixtures
  too, but copies the hub's columns and quoting by hand.
- Sending `v` and `c` unchecked: the hub drops them silently anyway, but
  a malformed value would then sit in the request for nothing.

## A site file's placeholders are filled by the dashboard, and the hub refuses any left over

**Id:** 7c1e4a52-9d3b-4f06-8a27-5e0b6c9f1d34
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-yjbzd8wvwz4n (the maintainer's request: values kept in the backend, `{{name}}`, the finished text stored, no way past the check); which texts the hub's rule leaves alone is this entry's reading
**Revisit when:** a public page has to quote a `{{name}}` literally, or a value has to differ by language

`{{name}}` in a site file takes its value from
`/admin/settings/site-values` in the dashboard, before the file is checked.
The hub stores finished text and never replaces anything; it refuses a text
still holding a placeholder on the landing page, legal and registration
writes, so a section's own import or a direct call cannot publish one either.

**Reason:** the template is in a public repository and the operator's details
are not, so they live in the instance. Stored text keeps what a visitor reads
fixed until the next import, as the request asks. `[Name]` collided with
Markdown links. The hub's rule also catches a slip such as `{{ Name }}`, which
would otherwise reach the page; it leaves `{{ .Values.x }}` and `{{#if x}}`,
which a page about a template language may quote and no site file's
placeholder can be. The rule catches a slip, not intent: `{\{name}}`, a
Markdown escape, passes and shows as `{{name}}`.

**Known limit:** a value goes in as written, so Markdown in it (`*`, backticks,
a link) takes effect where the placeholder sits in Markdown. HTML cannot get in:
the finished text passes the hub's Markdown check and the renderer escapes.
Values are one line, so none can start a block of its own.

**Rejected alternative:** the hub replacing on every read: a later value change
would rewrite published legal text with no new version. A check in the
dashboard alone: the request names other ways round it. Refusing every `{{`:
it would hit legitimate quoted text. A value per language: not asked for, and
a name per language does the same (`{{country_de}}`).

## The public pages are in ten languages, each translated and checked as a whole

**Id:** 4b8e2d71-6a0c-4e39-9f15-c27d3a6e8b02
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's list `en de fr es pt it nl ja ko zh-Hans`, passed on in the message on the card tsk-q5f23gacz1mp (seq 30343), and on the same card that the legal pages are translated too; how the list is carried and checked is this entry's reading
**Revisit when:** a language writes right to left, or a legal text has been reviewed by a lawyer

`landing.LANGUAGE_NAMES` carries the list and each language's own name, which
the language bar shows, since ten bare tags read as a code list. The page's
frame words are in `render.WORDS`. The instance's own site file holds every
text in all ten; a command line in the demo, an agent's handle and a cookie's
name stay as they are. `hub/tests/test_site_values.py` and the e2e step import
a neutral file with the same shape (`web/tools/site-fixture.json`), filled with
made-up values, and read every language; **Check the file** covers a real file
when it is imported.

**Reason:** the operator asked that the import works for certain. A wrong
placeholder in one language would otherwise show only on the live page.

**Rejected alternative:** Right-to-left support: no listed language needs it,
and it touches the stylesheet's every side. Traditional Chinese answered with
Simplified: `Accept-Language: zh-TW` goes on to the reader's next language.

The translated legal texts are machine translations, reviewed by nobody with
legal training. The English and German are not changed by them.

## An instance's site file is not in the public repository

**Id:** 68502afd-2713-4ea1-b341-73a6efb50537
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction on the card tsk-pfn7yg91d1y7, 2026-11-01, and the coordinator's word on the same card that **Check the file** is enough for the real file; the maintainer named no reason for the move
**Revisit when:** a public template for operators is wanted again
**See:** views.md#the-whole-site-is-one-json-maity-site1-checked-part-by-part-and-saved-in-turn-by-the-dashboard — 3b7c4d67-90b2-497a-9dd7-1f7a7ddfb7bd — as of 2026-11-01

The site file of the instance the project runs is kept outside this
repository, and an operator writes their own. Tests, smoke and e2e read
`web/tools/site-fixture.json`: every section type, all ten languages for the
landing and legal parts and two for sign-in and sign-up, with
placeholder text and the seven placeholders, none of an instance's words. Git
history keeps the old versions, and nobody rewrites it.

**Rejected alternative:** Tests skipped when no file is there: CI would no
longer cover an import in every language. A public copy of the instance's
texts kept as a template: that is what the instruction ends.

## The whole site is one JSON, maity-site/1, checked part by part and saved in turn by the dashboard

**Id:** 3b7c4d67-90b2-497a-9dd7-1f7a7ddfb7bd
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decisions req-0cv1n7eaegay (o1: one JSON for landing, legal and registration, dashboard only, no hub endpoint) and req-39vmjgrq5s32 (o1: a template in the repository, the imprint with placeholders only, landing-v3-complete.json dropped for one source; the template in the repository ended with 68502afd-2713-4ea1-b341-73a6efb50537, 2026-11-01), relayed by the coordinator on the card tsk-xw8a2hd84x3a, 2026-10-31; the coordinator's word that placeholders go in square brackets; the coordinator's decision on the review of #961, 2026-10-31 (an unknown key anywhere refuses the whole file; variants and campaigns stayed out while the editor's import did not know them, until the coordinator's decision on tsk-ets3x0c4ethg, 2026-11-01, took them in); the coordinator's decision on #961, 2026-10-31 (the template carries no registration; registration is the instance's own); docs/api.md §2.8.4 (a step-up holds 10 minutes); the dashboard's implementation, 2026-10-31
**Revisit when:** the hub offers one call that saves several settings in a transaction, or a fourth setting joins the site file
**See:** views.md#the-legal-pages-and-registration-import-and-export-json-too-text-not-loaded-stops-a-preview — 951ed7bf-6f23-4279-a4c6-f2c03c7c31ea — as of 2026-10-31

Since tsk-fct4awzw3k30 it stands folded at the top of the admin's **Pages**
tab, over the sub-tabs, as it spans them; `/admin/site` is gone without a
redirect (alpha), and `/admin/pages/site` opens it.

The instance admin has **Import or export everything** for the landing
page, the legal pages and registration as one file, `maity-site/1`,
extended language by language and imported again. Each part has the shape
its own section imports; a part the file leaves out stays as it is, and an
unknown format or key is refused by name. A check runs each part through
the call its section uses (the previews, registration's own check) and
lists it as changes, the same, not in the file, or refused. One Save then
runs the existing PATCHes in turn (each changed legal page, registration,
the landing page). The second factor is asked for once, since a step-up
holds for 10 minutes; each call still goes through the step-up helper, so
an expired window asks again rather than fails. A save that stops says
what is saved and what is not and goes no further, with no rollback. The
template that replaced `landing-v3-complete.json` has since left the
repository (views.md#an-instances-site-file-is-not-in-the-public-repository).
A site file need carry no registration: registration is the instance's own,
and a file imported whole would otherwise close an open registration without
a word.
Placeholders were first in square brackets, since the hub's Markdown rules
read `<Operator>` as an HTML tag and refuse the text; they are `{{name}}` now
(`docs/api.md` §16.7.3).

An unknown key anywhere in the file refuses the whole file, named by its
path, down to each part and legal page (deeper, in a page's languages or
the landing page's pages, the hub's preview refuses the part with its own
field names); a landing value of the wrong kind refuses its part. `variants` and
`campaigns` are in the landing part, as in the landing editor's import
(views.md#landing-variants-are-edited-one-at-a-time-in-the-landing-editor-campaigns-sit-beside-the-privacy-hint-their-counts-in-statistics);
the format's name stays `maity-site/1`, since a file without them still
means what it did and nothing has to read an older one. Export and Download read the three settings again first: the admin
page builds every section when it opens, so a file exported from that
first read would carry the state from before an edit in another section,
and importing it again would revert that edit.

**Reason:** one file for the whole site is what the maintainer works with,
and the dashboard can do it with the calls the sections already have, so
it needs no contract change and comes a day sooner. The site file is
refused as a whole when any key is unknown, at the top or inside a part:
a key the dashboard drops without a word looks saved to the person who
wrote it, and a typo in `enabled` would leave the public page in the
wrong state.

**Rejected alternative:** a hub endpoint that saves all parts in one
transaction, a day later and a contract change. Keeping the three imports
apart, which gives no "one file for everything". Placeholders escaped as
`\<Operator\>`, which the hub's check still reads as a tag where a space
follows the first word.

## The legal pages and registration import and export JSON too; text not loaded stops a preview

**Id:** 951ed7bf-6f23-4279-a4c6-f2c03c7c31ea
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-knb9me77f32t (the maintainer, 2026-10-31, after importing Landing V3: the same importer for the legal pages and registration); the coordinator's note that a preview of an imported but not loaded draft should say so instead of flickering (2026-10-31); docs/api.md §16.4, §16.7.1; the dashboard's implementation, 2026-10-31
**Revisit when:** the hub offers a dry check for the registration setting, or a PATCH of the legal pages may change several pages at once
**See:** views.md#the-landing-page-is-imported-and-exported-as-json-in-its-editor-an-import-is-checked-by-the-preview-call-and-saved-only-by-save — c174a492-2691-4887-9507-e1ba2e805a1f — as of 2026-10-31

Each legal page has its own Import or export JSON, for its languages (or
the same under the page's key). A load is checked by the page's preview
call and replaces the page's draft after a confirmation. Registration has
one for the body of its PATCH: a load fills the form after a
confirmation, keeps the fields the environment or the legal pages set,
and names a field the setting does not have. A field the JSON does not
name keeps what the form shows, typed and not saved included, since the
load starts from the form; an empty limit is left out of the export, so
an export always loads again. A legal page's load from a file of several
pages takes only its own and names the others. The hub checks the values
when the admin saves. Both editors share one part (`js/json-io.js`). In
every editor, the landing page's included, a preview while the JSON
field holds text that was neither loaded nor exported says so and opens
no tab.

**Reason:** a PATCH of the legal pages changes one page per call, so one
import per page matches what a save can carry. Registration has no
preview call, and a PATCH would save, so the form is the place to look
the values over. A preview of the editor's draft beside unloaded text
looked like a broken preview: the tab opened and closed at once.

**Rejected alternative:** one import for all three legal pages, which
would need three saves the admin does not see. Checking registration by
the real PATCH, which saves on success. Moving the landing editor onto
the shared part in the same change: its import also takes one page of
several and redraws the section list, so it keeps its own for now.

## The landing editor keeps its own copy of the hub's list of agents, and smoke compares the two

**Id:** dc4639b9-91bf-464e-8592-4009f935e46d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §16.7 (the agents a `works_with` section names are a fixed list in the hub's code); the card tsk-6wch92201m39; why a copy over a call is this entry's reading
**Revisit when:** the hub serves the list, or a second place in the dashboard needs it

The editor offers the agents of a **Works with** section from a list in
`js/landing.js`, the slugs and names of `AGENTS` in
`hub/src/maity_hub/landing.py`, in the same order. The check before a save
has the slugs as `LANDING_AGENTS` in `js/api.js`. `tools/smoke.js` reads the
hub's file and fails when either copy differs from it.

**Reason:** the contract serves no such list, and adding an agent is a change
in the code anyway, so a comparison catches a drift when it is made.

**Rejected alternatives:**
- An endpoint for the list: a contract change for one picker.
- A free text field for the slugs: every typing mistake would come back as the hub's refusal.

## Admin → Sign-in keeps the question for the mailed code open, and names no value it cannot take

**Id:** 7c2e5a14-9b3d-4f60-8a71-2d6e0b94c3f8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.6, §2.8.7, §2.8.8; `hub/src/maity_hub/auth/sign_in_settings.py`; PR #996's second part

The section (`js/admin-sign-in.js`) lists the sign-in methods with each value's source. **Mail for everyone** is in the list only while `missing` names neither `mail` nor `signing_key`, or while it is the current value, as the list would otherwise lie. Choosing it says that a code is mailed first and advises the admins to set up an authenticator app. The `PATCH` answers 202 and has changed that value only after the code: the form gives way to one question for the code with **Send again** (a new `PATCH`, which replaces the open confirmation) and **Leave it as it is**, which sends nothing, as nothing has changed and the code runs out. Other values changed in the same form are saved with the 202.

**Reason:** the contract makes the code the proof that a mail of this hub arrived, so the page must not read as saved before it. The refusals `mail_not_ready` and `no_verified_address` can still come, as the state may change after the page was read; they are said at the field.

**Rejected alternatives:** offering the value always and relying on the refusal: the contract says it is offered only while mail is ready. A cancelling `PATCH` on leaving: it would need a value to write back and a step-up for a change that never happened. Reading the settings again before showing the question: if that read failed, the mailed code would have no field.

## The words of sign-in and sign-up are instance content; the forms stay the dashboard's

**Id:** 133731df-a4ac-453d-923a-5df0878e69f0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's wish on tsk-fct4awzw3k30 and decision req-885kx86hhab4 on tsk-ya56x9gx986r, 2026-11-01; the plan the coordinator approved; docs/api.md §16.7.4

The site file gives `/login` and `/register` their pitch per language: title, subline, three points and a note. Every word of the forms comes from the dashboard's catalogue, which is translated with the rest of the portal, and the catalogue also supplies a key left out or a failed read. The hub chooses the file's language as for the landing page.

**Reason:** `next`, the device code's polling, the second factor and a session that ends under a page all live in the dashboard, so a second renderer would be a second sign-in path. No sign-in may depend on reading words.

**Rejected alternatives:** the dashboard taking its own language from `GET /auth/pages`: that answer picks among the languages the file has, so a form could change language with the instance's content; the dashboard draws in its own language and passes it as `lang`. A missing key filled from `default_language`: the answer would mix two languages under one `language`; the catalogue fills it, in the language the dashboard draws in. Form labels and buttons in the file too, with the file winning over the catalogue: two sources for one text, and an imported file would pin a form's words against later catalogue changes. The hub rendering the two pages as it does the landing page: a second path, above. Free HTML or sections from the file: the forms are a security surface. A format `maity-site/2`: it would invalidate files in use, and a part left out already stays as it is. Words in the `registration` part: those are settings, with their own environment rules. A table of its own with versions: unlike legal texts nothing needs to be proven later, so one setting row is enough.

## The sign-in and sign-up sub-tabs share one editor, and Save sends both pages

**Id:** 42fcba86-1e4e-43dd-b028-62de42cd1258
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** PR #1136 (tsk-fct4awzw3k30); docs/api.md §16.7.4: a `PATCH` of `/admin/settings/auth-pages` replaces the setting as a whole

`js/auth-pages.js` reads the setting once per admin page and both sub-tabs draw from one draft, so Save in either sends both pages. An empty field and a language without text are left out. JSON for one page is checked with `/check` (no second factor) before it reaches the editor, and only Save stores it. In the site file the two parts become one `PATCH`, at the first changed part; a part the file leaves out is sent as saved.

**Reason:** the hub has one row and no partial update. Two editors, each with its own read, would let a save in one tab overwrite what the other just saved.

**Rejected alternatives:** a `PATCH` per page: the contract has none, and the second would overwrite the first. Sending empty strings: the hub refuses them as `invalid`.

**Known limit:** like the landing editor, the draft is read when the Pages tab opens. After importing the whole site file in the same view, reload before saving in a sub-tab.
