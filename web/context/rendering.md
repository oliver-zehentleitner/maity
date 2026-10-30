# Rendering

## Everything an agent wrote is rendered as text; HTML-parsing DOM calls are refused by the lint

**Id:** ba30d469-65b0-4c83-ab90-a6e993c0ac33
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the dashboard's first implementation, 2026-10-21
**Revisit when:** messages or requests need formatting (Markdown, links) beyond preserved line breaks

The views build the DOM with `document.createElement` and `textContent`
only. `innerHTML`, `outerHTML`, `insertAdjacentHTML`, `document.write`,
`eval` and `new Function` are rejected by `make check`, so no string ever
reaches an HTML parser. Line breaks in message bodies are kept with CSS
(`white-space: pre-wrap`). Credential values are never shown anywhere:
an agent's credentials appear as id, creation date and a revoke button.

**Reason:** nearly every string on these screens was written by an agent
session — request titles, what it tried, options, chat messages — and an
agent can be steered by whatever it read. The human's dashboard session
holds the rights to answer consent-class requests and to revoke
credentials, so script injection there would be the cheapest way to
borrow those rights. Text-only rendering removes the class instead of
filtering it, and the lint keeps it removed.

**Rejected alternative:** HTML templates with a vendored sanitiser
(DOMPurify) — nothing on these screens needs markup yet, and the
sanitiser's bypasses would become this project's. Escaping by
convention without a lint — one forgotten call is enough.

## Links from data are https only; the join line lives in the join view and nowhere else

**Id:** 5b7f6472-086d-4d69-87a5-0030204b76bc
**Type:** constraint
**Status:** active
**Evidence:** confirmed
**Source:** the dashboard's reconciliation with docs/api.md, 2026-10-21
**Revisit when:** another URL field from the API is rendered as a link, or the join flow gets a second place that shows the line
**See:** rendering.md#everything-an-agent-wrote-is-rendered-as-text-html-parsing-dom-calls-are-refused-by-the-lint — ba30d469-65b0-4c83-ab90-a6e993c0ac33 — as of 2026-10-21

A URL that comes from data — a pull request link a member typed into a
release, say — becomes a link only when it is plain `https://`
(`Maity.dom.safeUrl`); anything else is shown as text. Since 2026-10-22
that also excludes a URL with user info before the host
(`https://bank.example@evil.example`) and one with control, bidi or
zero-width characters: each reads as one address and goes to another. The paste line a
join returns, with its single-use code, is kept in the join view's own
variables only: it is not stored in the page's storage, not put into the
URL, not logged, and leaving the view drops it.

An image source is never taken from data either (since 2026-10-22): a
project's logo and banner are loaded only from the hub's own path, which
the page builds from the slug and the ETag
(`/api/v1/projects/<slug>/logo?v=<etag>`, `docs/api.md` §11.2), or from an
object URL of a file chosen in the same tab; `Maity.dom.h` refuses any
other `src` — an `https` URL of another origin included (links may be https, images may not). The hub serves the image from its own origin and never lets
the browser load one from the forge.

**Reason:** text-only rendering stops markup, but an `href` is a second
way in: a `javascript:` URL typed into a release would run in the
human's session on one click. The join code is the one secret the
human handles in the dashboard (the root's credential rule allows it in
the pasted line only); the less of the page it touches, the fewer places
it can be read back from.

**Rejected alternative:** no links from data at all — the release list
is where the human checks a pull request, and a link there is what makes
it usable. A blocklist of schemes — `https` alone is the one the forge
uses, and an allowlist of one cannot miss a scheme.

## A member's picture is generated from its id, as SVG nodes, unless an avatar the page may load exists

**Id:** f6560be2-4153-4d19-adc7-6fdc8589991f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request for a picture that differs per member, relayed by the coordinator, 2026-10-22; web PR #128, 2026-10-22
**Revisit when:** avatars can be uploaded (docs/api.md #136) and an upload should replace the generated one everywhere, or a design asks for another pattern

Every member gets a picture: a mirrored 5×5 identicon and a hue, both
from FNV-1a of the member id, so every client draws the same picture for
the same member without asking the hub. It is built from SVG nodes
(`createElementNS`), never from markup, and it is decorative: the name is
always written beside it. The hue is set as a custom property through
CSSOM (`style.setProperty("--avatar-h")`); the theme sets lightness and
background, so it reads in light and dark. A member that carries an
`avatar_url` shows that picture only where `h()` lets the page load it
(the hub's own images); anything else falls back to the identicon.

**Reason:** a picture per member helps tell agents apart at a glance, and
deriving it from the id needs no hub field and no storage; SVG nodes keep
the rule that nothing from data becomes markup (see the entries above).
CSSOM instead of a `style` attribute keeps working under a strict CSP.

**Rejected alternative:** initials on a coloured disc — two agents named
"Agent B" and "Agent Builder" look the same. A hash-coloured `style`
attribute — blocked by a strict CSP and parsed as markup-adjacent text. A
picture from a third-party avatar service — it would send member ids out.

## Chat messages are Markdown drawn as DOM nodes by a small renderer of our own, never an HTML-producing library

**Id:** 854c8122-770c-4c80-be9f-0ce9c90c0d2e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's chat feedback (Markdown with code blocks and a copy button, no raw HTML), relayed by the coordinator, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** messages need tables or images, or another view wants Markdown beyond what the renderer covers

A chat message is drawn as Markdown by `js/markdown.js`: paragraphs
with their line breaks, headings (a line of strong text, not a page
heading), lists (a numbered one keeps its first number; nested by
indentation, bc7078b0), quotes (nested at most eight deep, deeper shown as written,
so a message of thousands of `>` cannot exhaust the stack), fenced code
(backticks or tildes, up to three spaces in, any info string whose first
word is the language) with a Copy button and a warning when the code
holds invisible bidi or zero-width characters, inline code (matching
backtick runs), strong and em, and links only where the target is plain
`https`; a link whose text looks like another address also says where
it goes. Every piece of text becomes a text node; raw HTML stays visible as
text, and anything not understood is shown as written. Quote puts a
message into the composer as `>` lines, which the renderer draws as a
quote.

**Reason:** what people paste into a chat with an agent is code, commands
and short lists; a dozen rules cover that. Building nodes keeps the rule
that nothing from data becomes markup (the entries above), so no
sanitiser has to be trusted.

**Rejected alternative:** a Markdown library that produces HTML plus a
sanitiser — a dependency from a CDN, and the safety of the page would
rest on the sanitiser's completeness. Plain text with `pre` wrapping, as
before — code and lists from agents were unreadable.

## Inline code copies itself on a click; no copy icon beside it

**Id:** e544d587-2aa0-4658-8771-c75e57b29422
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer on the card tsk-rdx6gaqveygx, 2026-10-29 (code from chat messages copied with one click: blocks with a button, inline code by a click or an icon, "Copied" as feedback); the dashboard's implementation, 2026-10-29
**Revisit when:** people report copying inline code they only meant to select, or a view needs inline code that is not copied

Inline code in rendered Markdown is a button (`role="button"`, focusable,
named "Copy <code>"): a click, Enter or Space puts its text on the
clipboard, and "Copied" stands beside it for two seconds as a status. A
click that ends a selection of text inside the code copies nothing, so
selecting part of it still works. Only a selection inside the code
itself stops the copy, and only on a click: a selection elsewhere on the
page must not swallow Enter or Space on a focused code span, which would
copy nothing and say nothing. Fenced blocks keep their Copy button, which says
"Copied" the same way. Both use one clipboard helper with one fallback
("Copy failed — select the text").

**Reason:** inline code in an agent's message is mostly a command, a
path or an id, the things one copies; a click on the code itself is the
shortest way, and it adds nothing to the line.

**Rejected alternative:** a copy icon after every inline code: a button
per span, which crowds a sentence with several commands and doubles what
a screen reader reads. Copying on a double click: it is the browser's own gesture for
selecting a word, so selecting part of a command and copying it would
fight each other.

## A picture is uploaded on the account, checked as the hub checks it, with no preview of the chosen file

**Id:** 3ec853f0-4141-4e81-acdf-c0fee94c920b
**Type:** decision
**Status:** superseded
**Superseded by:** 59aaf51f-c63d-4cb6-966b-85eb8f2c682d
**Evidence:** inferred
**Source:** the coordinator's card for the avatar upload (tsk-j4r5xbq5jp27) and docs/api.md §6.10, 2026-10-22; the dashboard's implementation, 2026-10-22
**Revisit when:** the hub's CSP allows `blob:` images, the accounts design gives linked forge accounts their own screen, or project admins get a say over pictures
**See:** rendering.md#a-members-picture-is-generated-from-its-id-as-svg-nodes-unless-an-avatar-the-page-may-load-exists — f6560be2-4153-4d19-adc7-6fdc8589991f — as of 2026-10-22

The human sets their own picture and their agents' pictures on the
account (`#/account/picture`, the profile menu's **Picture**), never in a
project's views. Before sending, the page checks the file the way the hub
does: the type from its first bytes (PNG, JPEG or WebP) and at most
1 MiB. It sends the raw body with the sniffed type and says the hub's
other refusals in words. What shows afterwards is the hub's own image,
loaded from `/api/v1/avatars/<id>?v=…`, the one avatar path `h()`
allows. There is no preview of the chosen file before the upload.

**Reason:** a picture belongs to the account or profile and is the same
in every project (§6.10), so it is set where the account is, not where a
membership is. Checking the bytes in the page saves sending a megabyte
the hub would refuse, and the wording matches the logo's upload. Without
a preview the page needs no new image source: the hub serves the page
under a CSP without `blob:` images. The hub also crops, scales and
re-encodes what it gets, so the stored image, not the chosen file, is the
honest preview.

**Rejected alternative:** a preview from an object URL before the upload.
The CSP blocks it on the hub, and it would show a file the hub then
changes. An editor in Members for project admins: §6.10 gives
`members:admin` no say over pictures, because a removal in one project
would remove the picture in all of them.

## Attachments: an image is shown from the hub's own path, every other file is only ever a download link, and nothing is previewed before it is sent

**Id:** 52e88bfb-69a5-4f6d-95e8-a2a3dd8acdd7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §8.7 (#166) and the coordinator's card for the dashboard's part (tsk-tfw5shzzp0kw), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub serves files from a separate origin, offers previews, or a browser is found to render a served file anyway
**See:** rendering.md#links-from-data-are-https-only-the-join-line-lives-in-the-join-view-and-nowhere-else — 5b7f6472-086d-4d69-87a5-0030204b76bc — as of 2026-10-23

A message's image is an `<img>` of `…/attachments/{id}/content` on the
hub's own origin. Every other file is shown as its name, size and type,
with a link to `…/content?download=1`, and nothing of its content is
shown: no preview, no viewer, no excerpt. The page lets `h()` use only
that path, built from the project and the attachment id, as a link or an
image source. A file is uploaded when it is chosen, and shows as pending
by name and size until the message is sent; there is no preview of the
chosen file. An image that does not load says so and keeps its download
link: a failed load is not known to be a deletion. One's own uploads that
no message names yet are read back from the hub in the composer, since
they count against the pending cap.

Known limits: after a reload, a non-image file deleted earlier still
shows as a download (the payload is not rewritten, §8.7; telling would
take a metadata read per file). The uploader of a file in a group chat
that has closed cannot delete it from here, because the payload does not
say who uploaded it. In fixture mode a chosen file's object URL keeps its
original type; its link downloads it.

**Reason:** the hub re-encodes images and serves every other file as
`octet-stream` with `attachment`, `nosniff` and a sandbox CSP, so the
browser renders nothing but the pixels of an image. A page that
previewed a file itself would undo that, because it would read the
bytes into its own origin. Uploading at once is the contract's two
steps: a failed post loses no upload, and the message names ids. A
preview of the chosen file would need `blob:` images, which the hub's
CSP refuses.

**Rejected alternative:** a text excerpt or a PDF viewer for files: the
contract excludes it, and it would parse untrusted bytes in the page.
Uploading only on Send: a large file would hold the message back, and a
failure would lose both.

## The theme is set on <html> by a script in <head> without defer; the dark tokens answer the system and an explicit pick

**Id:** ce73e8de-738e-4a8b-89ac-f98ef7d7ed81
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's ask for a light/dark switch next to settings and profile (tsk-9z69k7047w4h), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the theme is kept on the hub per human, or the CSP stops allowing the page's own scripts

Three choices, System (default), Light and Dark, in a header menu beside
the gear (signed in, since 2026-10-25, in Your account instead: views.md,
4faefa89-4543-48f1-a964-53574a6ded5d); the pick is kept per browser in `localStorage` (every access
in try/catch: without storage it holds for the page). `js/theme.js`
loads without `defer` from `<head>` and sets `data-theme` on `<html>`
before the first paint. The dark tokens are written twice, the same:
under `@media (prefers-color-scheme: dark)` for
`:root:not([data-theme="light"])`, and for `:root[data-theme="dark"]`.

**Reason:** every other script is deferred and would paint the page in
the system's theme first, then flip; the CSP (`default-src 'self'`)
allows the page's own script file but no inline script or style, so the
theme cannot be set inline. Writing the tokens twice keeps both paths to
dark in plain CSS, without a script to copy values.

**Rejected alternative:** setting the theme in app.js after load: a flash
of the other theme on every page load. A toggle of two states: no way
back to following the system once a choice was made.

## Ids in text are linked by their shape alone, and a title's ids are offered beside its button

**Id:** 3274d199-32a5-4dad-8926-ca8bfae7022b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's ask that an id in a request's text, or anywhere text is shown, be a link (tsk-dcj6qwjxc9cq), 2026-10-25; hub/src/maity_hub/ids.py (a prefix and 12 Crockford base32 characters); docs/api.md §6.13 (GitHub the one forge, the project repository's host); the dashboard's implementation, 2026-10-25
**Revisit when:** the hub gives another forge, another id shape, a page of its own to one card, or the designer reworks the inbox entry

`js/ids.js` turns `tsk-`, `req-`, `agt-` and `hum-` ids of the hub's
exact shape, and `#n`, into links in every text the dashboard renders
outside code (a code span that is one id alone excepted, 50234f88): the card on the board (`/<owner>/<slug>/tasks/<id>`, a route
that is the board with the card marked), the request in the inbox
(`/<owner>/<slug>/inbox/<id>`), the member in Members, and the repository's
`/issues/<n>` on GitHub. Nothing is looked up; the page an id opens says
when it holds no such thing. An inbox entry's title sits inside its
button, so its ids are repeated as links under **In the title** in the
open entry. A text with no project of its own (a personal request from a
project the human is not in, a chat read along from outside, `/observe`)
links none. Known false positive, accepted: a three-digit hex colour
(`#123`) links as a number.

**Reason:** one request per id to know whether it exists would cost a
read for every id in every text, and the page behind the link has to say
"not found" anyway. The exact shape (12 characters, no i, l, o, u) keeps
words like "tsk-1" or a path plain. A link nested in the entry's button
would be one control inside another, which keyboards and screen readers
cannot use. GitHub answers `/issues/<n>` for a pull request too, so one
URL fits both without knowing which it is.

**Rejected alternative:** fetching each id to show its title next to it:
the card asks for the id as the text, and the reads would multiply with
the text. Linking any `prefix-something`: fixture-like and typed ids
such as tsk-1 would become dead links. Moving the title out of the
button: it is the entry's name for the keyboard and for the list.

## Nested lists nest by indentation: further in than the item before opens a list inside it

**Id:** bc7078b0-df41-4068-a4e5-2fb2efeae898
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's report that nested lists in a chat stood at their parent's level (tsk-gx88t3myb81q), relayed by the coordinator, 2026-10-30; the rule's details are the implementer's, 2026-10-30
**Revisit when:** a list item needs more than its one line (a paragraph or code inside an item), or people report lists nesting where they did not mean them to

`js/markdown.js` reads a list item's indent (a tab counts four spaces).
An item indented further than its list's first opens a list inside the
item before it, numbered or not, whatever the outer one is; an item
indented no further than the list around ends the inner list; in between
it is one more item of the inner list. An item of the other kind at the
list's own indent ends the list, as before. Lists nest at most eight
deep, as quotes do; deeper items stay in the eighth list, so no message
can exhaust the stack.

**Reason:** a list with sub-points is how agents structure a report; drawn
flat, the sub-points read as points of their own.

**Rejected alternative:** CommonMark's rule that a child starts at its
parent's text column: two spaces under `1. ` is how many people and
agents indent, and it would stay flat there. Keeping lists flat (the
entry above, until now): the maintainer reported it as a fault.

## A code span that is one id alone links like the id in text; a project's full name before an id links into that project

**Id:** 50234f88-3120-47e7-8d20-8548d7ebe087
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's card tsk-9zqb4c3pxyac (a card id in text should open the card, not be copied), 2026-10-30; the coordinator's proposal on it (a code span of only an id links, code with more stays code), 2026-10-30; the review of #701 (a reserved first word as owner built a hub path and stopped the view), 2026-10-30; docs/api.md §6.25 (`<owner>/<slug>/<id>`); the implementer's choices for other projects and unknown ids, 2026-10-30
**Revisit when:** the hub serves a card by its id alone, without its project, or readers report a lone-id code span they meant to copy

Agents write ids in backticks. A code span whose whole text, spaces
trimmed, is one id with somewhere to open becomes the id's link, drawn
in the code face (`js/ids.js`, `only()`); a span with anything more,
such as a command naming a card, stays code that copies itself, and
fenced code never links. A card or request written with a project's full
name before it (`owner/slug/tsk-…`) links into that project, its text as
written; a bare id links into the text's own project, as before. A
prefix is a project only where its owner has a handle's shape and is
none of the first words the dashboard or the hub keeps for itself
(`api`, `join`, `impressum`, `admin`, … — `OWN_WORDS` in `js/app.js`),
and the link is only ever a path of the dashboard (`M.route.isRoute`);
otherwise the id stays text, so a title like `api/v1/tsk-…` can never
build a hub path that stops the view. A lone `#12` in backticks stays
code. Like every id, one with a full name links only where the text has
a project of its own; read along from outside, nothing does. Nothing
is looked up for any of them (3274d199): an id of another project or
none opens a page that says so.

**Reason:** a code span of only an id is meant as a reference almost
always; the reader wants the card. The full name is the one form that
says which project a card is in, and the hub keeps every project at its
full name's path.

**Rejected alternative:** linking ids inside any code span: a command to
copy would break into a link and pieces. Leaving every code span plain:
the card asks for the link. Looking an id up to find its project: there
is no route for a card by id alone, and one read per id would multiply
with the text.

## A contract's section is read when its card's panel is opened, shown as untrusted text, and never kept past a failed read

**Id:** c080f6ff-fb27-4d90-ba42-bff36df9085d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the card tsk-w31pgfy1ra7w and docs/api.md §6.8 (the text stays in the repository; the card view shows the section with ref, fetched_at and link; on not_found the unresolved place, never stale text), §6.14 (the repository's text is untrusted); the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** contract cards get a page of their own, the designer reworks the panel, or the hub sends the section with the card

The board shows each contract card's file and section in a folded
**Contract section**; opening it reads `GET …/tasks/{id}/contract` once,
Refresh again. The text goes through the chat's Markdown renderer
without a project, so neither mentions nor ids become links. A failed
read replaces whatever was shown with the card's place, the hub's reason
in words and its code.

**Reason:** a board with several contract cards would otherwise send a
forge read per card on every load, and the hub may answer each from a
60-second cache only; nobody reads every contract at a glance. Keeping
an older text after a failed read would show a contract the repository
may no longer hold, which §6.8 rules out. The repository's text is
written by whoever can push, so the dashboard adds nothing to it that
would make it act like a member's message.

**Rejected alternative:** reading every contract card's section with the
board: the cost grows with the board and buys text nobody opened. A
separate trusted renderer for repository text: the chat's renderer
already turns every piece into a text node.
## The landing page asks only at the root, falls back to sign-in silently, and is the one surface where Markdown links to routes

**Id:** b70e4ab6-5c55-47ba-96d7-d1b941157f63
**Type:** decision
**Status:** superseded
**Superseded by:** 528af98b-4c9b-44a5-98c8-ababb59e7ab9
**Evidence:** inferred
**Source:** docs/api.md §16.7 (the landing page can never stand between a person and sign-in; the card-body renderer extended by the dashboard-route link alone; title and cta label as text), the card tsk-gqcq7kwkxpgx; the dashboard's implementation, 2026-10-25; the designer was not asked yet
**Revisit when:** the hub serves images to visitors, or the designer reworks the page

Only the root without a session asks `GET /landing`; every other route
without a session, and `/login` always, is the login page. An answer
that is off, absent or a failure shows the login page and no error. The
Markdown goes through the chat's renderer, in which a module flag set by
`M.markdown.withRoutes` lets `[text](/…)` become an in-page link for
this one call; the chat itself still shows such a link as written.

**Reason:** a visitor who came to sign in must never meet an error or a
wait on a page that is content; asking only at the root keeps every
deep link exactly as fast as before. A route link written into a chat
message would point a reader at a page of the dashboard in someone
else's words, which the chat has never allowed; the operator's page is
the one place the contract allows it.

**Rejected alternative:** a separate renderer for the landing page: two
renderers would drift from the list the hub validates. Showing an error
on a failed landing read: it would stand between the person and sign-in.

## The landing page and the legal pages are edited in the admin area and rendered by the hub alone

**Id:** 528af98b-4c9b-44a5-98c8-ababb59e7ab9
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.7, §16.7.1, §16.11 (the hub renders the landing page at the root and the legal pages as static HTML, no script); the maintainer on the card tsk-ez7hpndp95bx, 2026-10-29 (the old Markdown editor goes); the coordinator's ruling on the preview and the contract for it (#628: a short-lived draft opened in its own tab), 2026-10-29; the hub owner's confirmation of the setting's shapes, 2026-10-29; the coordinator's review of #680 (the hub never sends `too_long`), 2026-10-30
**Revisit when:** an instance wants the landing page drawn by the dashboard again, or a draft needs a preview without a tab of its own

The dashboard draws neither page for a visitor: without a session the
root is the hub's static page or, with the page off, the login page, and
the dashboard never asks `GET /landing`. The login and registration
pages link to the legal pages that are set, from `GET /legal`. In the
admin area **Landing page** edits the setting per language: the page's
title and description, its sections of the contract's types in their
order (add, move, show or hide, remove; items within a section the same
way, and so each named list of the newer types, `demo`'s
`terminal_lines` and `steps` and `opensource`'s `tiles` and `links`, a
list of an exact length offered without Add or Remove below it;
`activity` and `collab` kept as they are, never offered), and the
footer for all languages. A save sends the whole draft in one `PATCH`;
the hub's refusal names fields by their path
(`pages.de.sections.2.items.0.title`), and each is said at the field of
that path, a path without a field in the status line. A field the
hub refuses as `invalid` with a limit reads "empty, or longer than
allowed (…)": the hub answers `invalid` for both, never `too_long`, so
the editor cannot tell them apart; naming only the limit was rejected
because it misleads at an empty field, and a title with a tab or a line
break is `invalid` too, which the wording does not name. **Legal pages**
edits each page per language and saves one page per call, which the hub
keeps as a new version; a page is taken down with `null`. **View as a
visitor** opens the saved landing page at `/?as=public` in a tab of its
own, offered only while the page is on. **Preview the draft** posts the
draft (`POST …/landing/preview`, `…/legal/preview?page=`), which the hub
checks as a save and keeps for 10 minutes, and opens the `url` it answers
in a new tab, opened at the click so no pop-up blocker stops it; the
address is taken only when it is the hub's own preview path.
The renderer's mode for path links (`M.markdown.withRoutes`) went with
the dashboard's landing page.

**Reason:** one renderer for visitors, the hub's, so what the editor
saves is what a crawler and a person see, without a script; the field
paths let the editor say a refusal where it belongs, however deep in a
section.

**Rejected alternative:** a preview drawn by the dashboard's own
renderer: it would look like the hub's page and drift from it. The
hub's HTML fetched and shown in a frame (`srcdoc`) or from a blob URL:
it would run under the dashboard's policy, not the page's, the reason
pictures are never previewed either (3ec853f0). Saving a
section or a language at a time: the contract replaces the fields it
names, and one draft keeps the order and the default language
consistent across a save. Keeping the Markdown editor beside the
sections: two forms of the same page (the alpha rule).

The editor depends on the hub's sections shape and legal pages (#631)
and on the preview routes and the root's `?as=public` (#628's contract
and its hub change); until those are on main, its saves are refused
and its preview has no address, so it is merged after them.

## A hub whose attachment store is off hides Attach files and is not asked again

**Id:** 831e6402-6484-42a6-971a-0cafd0e7ecb4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (the contract change #464: without `MAITY_ATTACHMENT_DIR` every attachment call answers `409 attachments_not_configured`); the dashboard's reading of it is the implementer's; the coordinator's ruling on tsk-gn9w6mwazfyd (alpha rule: the 404/405 branch removed), 2026-10-30
**Revisit when:** an operator can switch the store on without reloading the page, or the hub tells the dashboard which parts it has before it asks
**See:** rendering.md#attachments-an-image-is-shown-from-the-hubs-own-path-every-other-file-is-only-ever-a-download-link-and-nothing-is-previewed-before-it-is-sent — 52e88bfb-69a5-4f6d-95e8-a2a3dd8acdd7 — as of 2026-10-27

`web/js/attachments.js` took a `404` or `405` for "this hub has no attachments"
and stopped asking until the page was loaded anew. A hub that has the
routes but no store answers `409` with the code `attachments_not_configured`
to the same calls, and the e2e run counted that as a problem on a page that
does nothing wrong. The same check now covers that code, so the Attach files
part is hidden and the listing of waiting files is not asked for again.
Since 2026-10-30 only that `409` counts: the `404`/`405` reading for a hub
without the routes was a compatibility branch for hubs before #464, which
the alpha rule removes, and such an answer is now an error like anywhere
else.

**Reason:** to the person at the page the two hubs are the same: no files can
be sent. The dashboard should not report an operator's choice as a fault.

**Rejected alternative:** switching the store on in the e2e run only: the page
would still treat an unconfigured hub as broken in production.

## A link in one's own chat bubble takes the text's colour, underlined

**Id:** bf8a5722-3f5f-4265-a89b-5ed34622aded
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the e2e's accessibility check (axe-core, color-contrast) on the first real attachment upload, card tsk-8h6yzp4f8jqg, 2026-10-30: the accent #1a66d9 on `--out-bg` #dbe9ff at 4.33:1, below 4.5:1, and below it in the dark scheme too; the review of #673
**Revisit when:** `--accent` or `--out-bg` change, or own messages get a background of their own per scheme

`.msg.out a` takes `var(--text)` and stays underlined: any link in one's
own bubble — an attachment's, a Markdown link, an id's link — reads
13.2:1 on `--out-bg` in the light scheme and 10.9:1 in the dark one.
Links everywhere else keep the accent.

**Reason:** the bubble's tint is what makes one's own messages stand
apart, and the accent fell under WCAG AA on it in both schemes. The
underline keeps a link recognisable without its colour.

**Rejected alternative:** a darker accent for every link: it would
change every link and button of the dashboard for one background, and
the accent's own ratios on `--bg` and `--surface` were measured and
documented. A link colour of the bubble's own per scheme: another token
to keep in step with both backgrounds, for what the text's colour
already does with room to spare.

## The landing page's one script only adds motion, the theme switch and tabs, by hooks the hub's template carries

**Id:** 515a9304-a7fd-4d81-953a-3f5c253ab9a5
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §16.7 after the contract #737 (progressive enhancement: at most 10 KiB, `defer`, no request, only the page's own DOM, never database content as HTML, nothing under `prefers-reduced-motion`); the designer's handover for landing V3 stage 1 (`landing.js` sets `.demo-on` by IntersectionObserver, `data-theme` with its button and localStorage, `.scales-tabs`; rings and loader by CSS); the hooks agreed with the template's implementer on the card tsk-m6ew67r1w3hc, and the file in the hub's package so a hub without the dashboard serves it, 2026-10-30; the card tsk-xtyr12836zwa
**Revisit when:** the landing page gets stage 2 (the public feed), or the template's hooks change

`hub/src/maity_hub/landing_assets/landing.js` does four things and no
other: shows the theme button (`[data-lp-theme]`, hidden in the HTML)
and switches `data-theme` on the root, kept in `localStorage` only; adds
`.demo-on` to a `.demo` section while it is on screen, so the CSS plays
the demo's loop; turns `.scales` columns into tabs (`.scales-tabs`, the
tab names taken from each column's first `h3` as text); and counts
`[data-lp-count]` up to the number the page holds, putting the page's
own text back at the end and leaving any text that is not a plain number
alone. Under `prefers-reduced-motion` neither the demo loop nor the
counting starts. A stored theme is set when the script runs, after the
first paint (`defer`, and the page's policy allows no inline script), so
a visitor whose choice differs from the system's sees the system's theme
for a moment. `web/tools/check.py` checks the file with the
dashboard's rules, its size and the absence of any request.

**Reason:** the page is complete and readable without it (§16.7); every
look stays in the CSS the designer wrote, so the script holds no
styling to drift from it. Hooks named on both sides once keep the
template and the script apart: neither builds the other's markup.

**Rejected alternative:** typing the demo's lines from script (writing
text node by node): the CSS loop already does it from the HTML, and the
script would then hold the timing a second time. A class that switches
all motion on (`.lp-motion`): the rings and the loader are pure CSS and
stop under reduced motion by the stylesheet itself. The file under
`web/landing/`: a hub serving only the landing page, without the
dashboard's files, would have no script.

## Words come from a catalog per language, one key per sentence; new text in the views is held back by a ratchet

**Id:** adaebd69-6541-4f4c-81ce-8c38f1fb70aa
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's card tsk-k9j3nxcw9htw, 2026-10-29 (multilingual support comes last, but what saves rework later is done now: a catalog function reading a static file per language, never the database; Intl for dates and numbers; no assembled sentences; a check that flags new strings in views if it can be done without noise; old strings move over view by view); the coordinator's instruction to land the mechanism and the check first, the views in small PRs after, 2026-10-30
**Revisit when:** a second language is added, the account gets a language and locale of its own, the hub's WORDS move to per-language files, or the hub adds a role or trust (its sentence gets a key; the neutral one stays only the fallback)

`js/i18n.js` gives `M.t(key, values)` over `window.MAITY_I18N[lang]`,
which `js/i18n/<lang>.js` sets; `tools/check.py --write` builds that file
from `i18n/<lang>.json`, as it builds the fixtures' bundle, because a
page from `file://` cannot fetch JSON. The bundle sits under `js/`, the one script
directory the hub serves at `/assets/` besides `css/` and `brand/`
(`hub/src/maity_hub/shell.py`), so it needs no hub change; the JSON
beside it is the file a translator edits. A text is a string or plural
forms chosen by `Intl.PluralRules`; a number in a placeholder is
formatted for the locale; a key the catalog lacks reads as itself.
`M.fmt` formats dates and numbers with `Intl` in `M.i18n.locale`, the
browser's own until the account sets one. `make check` ratchets the
views: a file may hold no more prose string literals than
`tools/strings-baseline.json` allows, `--write` only lowers that count,
and a new file starts at none. A count is raised only by an edit of the file by hand,
with the reason in the commit (as for #741, #746, #740, #753 and #757, which
added text before the ratchet landed). The baseline is taken from main
at merge time, not from the branch's base: every view PR that lands
first raises its file's count, so a ratchet PR merges main last and
raises those counts by hand with the reason. Rejected: computing the
baseline in CI from main, which would accept every new string and hold
nothing back. English is the only catalog; the first
keys are the chat's instance choice. A label kept in a table at load time
(the tabs, the states, a field's rules) is a getter that calls `M.t`
when it is read, so a language set after the page loads still applies.
A sentence that holds a link or a member
is `M.tn(key, values)`: the same text as pieces, each node placed where
the language puts its placeholder, never a sentence cut around a link.
A list inside a sentence is joined with `Intl.ListFormat` in the
catalog's language, so from three names on English reads "@a, @b, or
@c", not "@a or @b or @c": the order and the commas of a list differ
between languages. A Node tool that runs `dom.js` in a `vm`
(`tools/starter-configs.js`) loads `js/i18n/en.js` and `js/i18n.js`
first, in the order of `index.html`, and hands the context `Intl`:
`dom.js` calls `M.t` while it loads. Rejected: a fallback in `dom.js` for
a missing `M.t`, which would let the page and the tool drift apart.
A value from a set the hub defines (the ticker's types, a reason's role
or trust) is one key per value, the sentence whole with the language's
article ("you are an owner"); a value the hub adds later reads as a
neutral sentence ("you have the role {role}"). Rejected: choosing "a"
or "an" in code, which only English has. A count said with a word ("3 in
progress" in the board bar's name, "2 urgent") is one key per word with
`{count}`, not the label lowercased after a number. A key that counts
has its plural forms even where English writes them alike ("Earlier
joins ({count}): …", "{count} urgent"): another language may not, and the
form chosen by `Intl.PluralRules` is there to be translated. A key per value also lets a
value read in its own words ("you work in ops", not "you are an ops").
Not in the catalog: the runner's starter configuration
(`runners.js`), a file the runner reads and `tools/starter_configs.py`
checks as written, with commands and product names. Still put together from
pieces: a status line's prefix and its reason ("Not saved: " + the
hub's words, `status.fail`), for a later part of stage 2.

**Reason:** translating later is then filling a file, not finding and
splitting sentences in code. A per-file ceiling stops new text in code
without flagging the hundreds of old strings at once, and it is quiet:
it fails only where a count grows.

**Rejected alternative:** fetching `i18n/<lang>.json` at run time:
fixture mode runs from `file://`, where that fails, and it is one more
request before anything is drawn. A translation library from a CDN: a
dependency for a lookup of a few lines, against the page's policy of
first-party scripts only. A check that fails on every prose literal: it
would fail on today's code until every view had moved. Sentences put
together from translated pieces: word order differs between languages,
so those pieces cannot be translated on their own.

