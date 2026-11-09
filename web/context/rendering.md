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
**Status:** needs-review
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

## An avatar shows the generated picture at once and loads the hub's picture only near the screen, at the size shown

**Id:** 4db0d863-545e-46bb-b031-b5c9bbbfacb8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the lead's plan for the avatar card (tsk-vvyqmk9vwg8e), 2026-11-09; a local reproduction of a board's burst of avatar reads against a hub on PostgreSQL, 2026-11-09
**Revisit when:** the hub serves a board's avatars without queueing (one read for all of them, or a picture inside the list's answer), or browsers lazy-load images that are not yet on the page
**See:** rendering.md#a-members-picture-is-generated-from-its-id-as-svg-nodes-unless-an-avatar-the-page-may-load-exists — f6560be2-4153-4d19-adc7-6fdc8589991f — as of 2026-11-09

`M.avatar` returns the identicon every time. When the member carries an
`avatar_url` the page may load, it loads that picture once the identicon
is within 200 px of the screen (IntersectionObserver; without one, at
once). It asks for the smallest size the hub serves (§6.10, Sizes: 32, 64,
128, 256) that covers the shown size on this screen, with the device pixel
ratio capped at 2. The loaded image takes the identicon's place with the
same size and class rules. A picture that does not load leaves the
identicon. A logo or banner is loaded as given, without a size. `h()`
allows the sized address and no other parameter. The observer watches
only placeholders that are on the page. One that is not (built before its
view is mounted, or taken off the page) is held only through a `WeakRef`,
and is watched again once it is on the page: a sweep runs after every
change of the page (a MutationObserver, once per frame) and at every
avatar drawn. A view that is thrown away keeps nothing alive, and one that
is mounted late still gets its pictures.

**Reason:** a board draws about 35 avatars, and the hub answered them one
after another in effect (about 380 ms in the browser for 52 ms in the
hub). Until then the page showed empty boxes and laid out late. With the
identicon first, nothing waits for the pictures. Loading only near the
screen leaves the reads of long lists to the rows someone scrolls to. The
size cuts the bytes: a 16 px avatar fetched 256 px.

**Rejected alternative:** `<img loading="lazy">` in place of the
identicon. The browser leaves it empty until the picture arrives, and a
detached image is never lazy-loaded, so the identicon could not stay in
its place. A wrapper holding both the identicon and the image: the CSS
rules for avatars (clipping on cards, overlap in a row of avatars) select
`.avatar-svg` and `.avatar-img` directly, and a wrapper would break them.
Letting a placeholder go only once the observer had seen it on the page:
a view drawn twice before the observer's first callback left its first
placeholders observed for good. Letting go of every placeholder still off
the page 10 s after it was drawn: a view mounted later than that (the
board waits for a card's own read before it is mounted) kept the generated
pictures for good (both from the review of #1541).


## Chat messages are Markdown drawn as DOM nodes by a small renderer of our own, never an HTML-producing library

**Id:** 854c8122-770c-4c80-be9f-0ce9c90c0d2e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's chat feedback (Markdown with code blocks and a copy button, no raw HTML), relayed by the coordinator, 2026-10-22; the dashboard's implementation, 2026-10-22; card tsk-qzvb0c0abm3a (bounded work per line, 2026-11-04)
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

Its work on one line grows with the line's length, since the contract
view (§6.8) draws files of up to 4 MiB with it (card tsk-qzvb0c0abm3a).
Each backtick run's closing run is found from a table built once per
line; the search from the start for every run grew with the square of
the runs. A link's target holds no `[`, as in the hub's renderer
(§16.7): what one `[` reads ends at the next, where a target to the
line's end was read again from every `[`; such a target's brackets stay
text, and the address inside them is a bare link. Nodes are appended
one by one, since spreading a long line's thousands of them into one
`push` overflowed the call stack.

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
account (its Profile tab, `#/account`; `#/account/picture` leads there), never in a
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
**Source:** the maintainer's ask that an id in a request's text, or anywhere text is shown, be a link (tsk-dcj6qwjxc9cq), 2026-10-25; hub/src/maity_hub/ids.py (a prefix and 12 Crockford base32 characters); docs/api.md §6.13 (GitHub the one forge, the project repository's host); the dashboard's implementation, 2026-10-25; tsk-8nbw39n0snsd for a reference after a slash
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
(`#123`) links as a number. A reference right after a slash links only
when the reference before that slash matched (`#909/#911`), so a path or
URL stays plain; the check is in the loop, since a regular expression's
lookbehind cannot know whether the earlier reference was itself accepted.

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
button: it is the entry's name for the keyboard and for the list. Keeping
`/` in the lookbehind: `#909/#911` would link only the first. A lookbehind
for `/` after a reference: it matches `issues/#5/#6`'s `#6` too, since it
cannot know whether `#5` was itself accepted, so the check sits in the loop.

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

## The whole contract is read when its view opens and on Refresh, revalidated by the browser's cache, its headings anchored by the hub's table of contents

**Id:** 8add3ca1-172f-4482-b2ec-d8d45d63a557
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §6.8 ("The whole contract": `toc` with `anchor` and `line`, `ETag` and `Cache-Control: private, no-cache`, read when the view opens and again only on Refresh, an error shows the path and the hub's reason); web/js/contract.js, web/js/markdown.js `opts.anchors` and `atxTitle`; the cards tsk-6jz07t0080rk and tsk-qzvb0c0abm3a
**Revisit when:** the hub's heading parser and the dashboard's renderer part ways on what a line is, the designer reworks the view, or the dashboard gets its own cache layer

`/<owner>/<slug>/contract` reads `GET …/contract` once when it opens and
again only on Refresh, never on a poll. It sets no `If-None-Match`
itself: the answer's `Cache-Control: private, no-cache` makes the
browser keep it and revalidate it on every read, so an unchanged file
comes back as a 304 the page never sees, without its bytes. The text
goes through the chat's renderer without a project, as a card's section
does (the entry above). Its headings are not found by the renderer:
`opts.anchors` maps each `toc` entry's `line` to its level and anchor,
and that line is drawn as a real heading with the anchor as its `id`,
its section number a text of its own. Before rendering, the view turns
every line separator Python's `str.splitlines` knows into a line break,
so the hub's `line` and the renderer's count are the same. An error
replaces the page with the path and the hub's reason.

An anchored line's title is cut as the hub cuts it (`contract_text._atx`):
up to three spaces, the marks, the title without a closing `#` run after
a space or a tab. `atxTitle` does it in string steps, one pass over the
line each, as the hub does since the same card: a file of up to 4 MiB
may hold one long line, and the patterns before them tried every start
in a run of spaces, which grew with the square of the run. The title is
the old pattern's, checked against it as an oracle on short lines, and a
smoke case reads three headings with 128 KiB of spaces each in bounded
time.

**Reason:** a file can be a megabyte, so a poll would cost the forge and
the hub a read every time, and the browser's cache already does what
§6.8 asks of a re-read. Anchors taken from the hub's `toc` are the ones
a contract card's section links to; a second parser in the dashboard
could disagree with the hub on a fence, a closing `#` run or a duplicated
number, and the link would land nowhere.

**Rejected alternative:** an `ETag` store in the view that sends
`If-None-Match` and keeps the last text for a 304: it repeats what the
browser does, and a text kept in the page could outlive a failed read,
which §6.8 rules out. Anchors from the renderer's own heading
detection: the chat's renderer turns `####` into no heading at all, and
any difference from the hub's parser breaks the card's link.
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

## English is always loaded; the reader's language comes as its own script, chosen by one rule in one place

**Id:** 7e1c4f02-6a3b-4d55-9b1e-2f0c8d7a41b6
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-ya56x9gx986r, 2026-11-01; card tsk-7dty3gkegqgc, 2026-11-04; docs/api.md §6.2; `en.json` holds 3326 keys, 208 KB, 54 KB compressed
**Revisit when:** a language's file grows so that its load shows on the first paint, or a catalog is complete enough that English need not come with it

`js/i18n/en.js` stays in `index.html`, since a key without a translation reads in English. Another
language is one script more, loaded before the first view (`M.i18n.ready`), only if
`js/i18n/languages.js` names it, so no value from an address ever becomes a script's path.
`M.api` hands every answer of `GET /auth/session` to `M.i18n.follow`, and a 401 hands it null, so
every view, the invitation's and the registration's among them, gets the same rule without asking.
Plural forms follow the catalog's language, not the locale of the numbers: a German browser reading
the English catalog needs English forms.

The registration sends `interface_language` only for an explicit choice (the picker on `/register`,
or `?lang=`, unless the landing page's frame overrode that `?lang=`: fc89488b-2c14-4e1c-8dc1-4e1b5f6a8f17). Without one it leaves the field out, so the account keeps
`null` and goes on following the browser.

`?lang=` is read on every call of the rule, so a choice made on the page (`M.i18n.choose`: the
pickers on `/login` and `/register`, the frame's languages) also writes its tag into the address
(since 2026-11-07 also one without `?lang=`: 323db387-6c53-4a63-86bd-13a464b114e7), through `M.route.go` with `quiet`, which replaces the address without
drawing the view again. The frame's links lead to `/register?lang=<the frame's language>`, and `/register`
reads the session again when it is drawn: before, its 401 read the older `?lang=` back, and the
page jumped back to the language it was reached in (tsk-7dty3gkegqgc; on `/login`, a reload did).

**Reason:** the visible language must be known before a view draws its words, and several views read
the session themselves. A catalog per language keeps nine languages off every page load.

**Rejected alternatives:**
- Always sending the page's language at registration: every account would get `en` while it is the
  only catalog, which later could not be told apart from a real choice, and the hub's mails would then
  ignore `language` (§6.2).
- All ten in `index.html`: about 2 MB of script before anything is drawn, for one language used.
- Asking in `render()` after its session read: `invite.js` and `register.js` draw before that line.
- Picking the language in the hub before sign-in: the dashboard chooses and passes `lang` to the
  page texts (§16.7.4). (The first reason, a choice kept in the browser, is gone since 2026-11-07:
  323db387-6c53-4a63-86bd-13a464b114e7.)
- Reading `?lang=` only once, when the dashboard loads: an address with `?lang=` would then say
  another language than the page, and a reload would still take the choice back.
- Writing `?lang=` into every address on a choice, also one without it: rejected while the choice was
  kept in the browser; adopted on 2026-11-07, once nothing is kept there
  (323db387-6c53-4a63-86bd-13a464b114e7).
- `M.route.go` without `quiet`: it draws the view again while the picker's page draws itself,
  so what was typed into the form so far would be lost.

## Before sign-in the dashboard takes the landing page's order for the language, and keeps nothing in the browser

**Id:** 323db387-6c53-4a63-86bd-13a464b114e7
**Type:** decision
**Status:** superseded
**Superseded by:** fc89488b-2c14-4e1c-8dc1-4e1b5f6a8f17
**Evidence:** confirmed
**Source:** card tsk-a9n9p6952wwb (landing in English, sign-in and visitor views in German for the same visitor, 2026-11-06), reproduced on maity.team 2026-11-07; the lead's go on the plan (Maity message, 2026-11-07); `web/js/i18n.js`, `hub/src/maity_hub/render.py` `choose_language`
**See:** rendering.md#english-is-always-loaded-the-readers-language-comes-as-its-own-script-chosen-by-one-rule-in-one-place — 7e1c4f02-6a3b-4d55-9b1e-2f0c8d7a41b6 — as of 2026-11-07
**Revisit when:** the maintainer wants a visitor's choice kept across visits, the hub's public pages start reading a language cookie, or the dashboard takes the visitor's language from `GET /site/chrome` (which closes the gap below)

Without an account's `interface_language` the dashboard takes the landing page's order: `?lang=`,
then the browser's languages, then `en`. The landing page itself offers only the languages it has a
page in, takes `?lang=` only as an exact offered tag where the dashboard reads the closest catalog
(`de-AT` reads `de`), and falls back to its `default_language`, not to `en`
(`render.choose_language`, `render.best_language`, §16.7). A choice made on a page (`M.i18n.choose`) holds
for the page while it lives and writes `?lang=` into the address, also one that had none; the
frame's and the landing page's links carry `?lang=` from page to page. Nothing goes into
`localStorage`: the key an older version wrote, `maity.language`, is removed once when the
dashboard loads, and no other key is touched.

**Reason:** a choice kept in `localStorage` is invisible to the pages the hub renders itself. After
one visit to `/signin?lang=de` an en-US browser got the landing page in English and the sign-in and
visitor views in German, in the same visit. One rule that both sides can read is the fix.

**Consequence:** a visitor who chose a language and later types a bare address gets the browser's
language again, on every page alike. An address copied from a page after a choice carries
`?lang=` and opens in that language, as the landing page's links already do. Two gaps remain. Where
the fallbacks differ: with `default_language: de`, a browser asking only for a language without a
landing page (`sv`) gets the landing page in German and the dashboard in English. Where the offered
sets differ: with `default_language: en` and pages only in `en` and `fr`, a browser asking for `de`
gets the landing page in English and the dashboard in German, and one asking for `de, fr;q=0.8` gets
it in French and the dashboard in German (likewise `?lang=de-AT`). The two agree only where the
landing page has a page in each of the ten languages and `default_language` is `en`, as on
maity.team. Closing both means taking the visitor's language from `GET /site/chrome`, which the hub
chooses exactly as the landing page's; that is a change of behaviour, left to a card of its own
rather than to the review of this one.

**Rejected alternative:** a language cookie the hub reads too: it would keep the choice across visits,
but the public pages set no language or tracking cookie (context/scope.md, hub/context/landing.md;
`/` reads only the session cookie, to choose between the landing page and the dashboard), and
`GET /site/chrome` and `GET /auth/pages/{page}`, which vary on `Accept-Language` only, would need
`Vary: Cookie`. Keeping the choice across visits is the maintainer's call, and it is that cookie.

## Before sign-in the dashboard takes the landing page's own language from `GET /site/chrome`

**Id:** fc89488b-2c14-4e1c-8dc1-4e1b5f6a8f17
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-jh94ax9pphxs, the follow-up 323db387 named, and the gaps the reviews of #1463 found (2026-11-07); the lead's go on the plan and on the revised hook, with the redraw accepted and a short timeout required (Maity messages, 2026-11-07); `web/js/i18n.js`, `web/js/site-chrome.js`, `hub/src/maity_hub/render.py` `choose_language`
**See:** rendering.md#before-sign-in-the-dashboard-takes-the-landing-pages-order-for-the-language-and-keeps-nothing-in-the-browser — 323db387-6c53-4a63-86bd-13a464b114e7 — as of 2026-11-07
**Revisit when:** `GET /site/chrome` stops choosing its language as the landing page does, the maintainer wants a visitor's choice kept across visits (that is a language cookie, 323db387), or the read's cost or delay shows on signed-out pages

Without an account's `interface_language` the dashboard takes the landing page's own language.
On the 401 of `GET /auth/session`, which every view without a session waits for, `i18n` reads
`GET /site/chrome` once per page and address, with the address's `?lang=` as written (or the last
one this page saw, or a pick on it, across routes without one) or without `lang`, and takes its
`language`: the hub chooses it from the exact `?lang=`, `Accept-Language`,
the landing page's languages and its `default_language` (§16.7.5). The frame on `/login` and
`/register` reads the same address (the browser's cache answers it) and its `language` counts the
same way; where it differs from what the page was drawn in, the page draws itself again once, never
when they agree. Precedence: the account's language, then a choice made on the page (it holds for
the page's life, until an address with any other `?lang=` value, as `sv`, `xx` or `de-AT` after
a pick of `de`), then the
frame's, then `?lang=` (the closest catalog), the browser's languages and `en`. A signed-in account
without an `interface_language` (the session read answered 200) is no visitor: it keeps the
browser's rule and never reads the frame. Nothing goes into the browser's storage, as
323db387 decided. The read is given `i18n.frameWait` (1500 ms): a failed or late answer leaves the
rule without it and holds no view; fixture mode reads nothing, its frame answering English whatever
is asked.

**Reason:** the reviews of #1463 showed the dashboard's own rule could only approximate the landing
page's: the landing page offers only the languages it has pages in, takes `?lang=` only as an exact
offered tag and falls back to its `default_language`. Asking the hub, which already chooses the
frame's language that way, makes them one choice instead of two that agree only with all ten pages
and `default_language: en`.

**Consequence:** a reload with a `?lang=` the landing page has no page in (pages `en` and `fr`,
`?lang=ko`) follows the landing page, though the address still shows `?lang=ko`, as the landing page
itself does; only a choice made on the page holds against the frame, for that page. Such an
overridden `?lang=` is no choice of the person's either: `/register` does not store it as the
account's `interface_language`, or the account would read Korean while the landing page reads
English, the split this entry closes. Every signed-out
page load costs one more `GET`, `Cache-Control: public, max-age=60`.

**Rejected alternatives:**
- Waiting for the read before every visitor view: a slow hub would delay every signed-out page;
  the short timeout keeps the delay bounded instead, and the redraw is only where the two differ.
- Reading the frame before `M.i18n.ready`, on every page load: also for signed-in readers, who never
  need it, and before the session says whether there is one.
- Reading it only where the frame is drawn (`/login`, `/register`): the visitor views, which the card
  was about, would keep the gap.
- Restricting the pickers to the landing page's languages while the frame stands: a person may
  still want a dashboard language the landing page lacks; their choice holds for the page instead.

## A missing translation is a note until the release; a wrong one fails at once

**Id:** 3d9a6c17-52e8-4b0f-a7c4-91e6f2b08d35
**Type:** decision
**Type:** workaround
**Status:** active
**Evidence:** inferred
**Source:** card tsk-ya56x9gx986r, 2026-11-01; docs/api.md §6.2 (a key without a translation reads in English); main after #1285 and #1284, fixed in #1296 (2026-11-03); the merge-time check from the reviews of #1298 and #1300 (2026-11-03)
**Revisit when:** the release workflow of the hub runs `make release-check` itself, a language with other plural rules joins the ten, or CI checks a pull request's merge with the current main (the workaround then goes)

Placeholders that differ, a key English lacks and impossible plural forms fail `make check`, since
they break a sentence on screen. A missing or out-of-date key fails only `make release-check`: every
English text a PR adds would otherwise have to arrive in ten languages in that PR. Which English a
translation follows is kept per key as two hashes in `i18n/<lang>.meta.json`, its own text beside the
English: when the translation's text changes it follows today's English, with no step to remember.

The other side of this: a key English drops fails `make check` in every language that still has it.
Two PRs that each pass against an older main can therefore turn main red together, in either order: a
translation PR that lands after the PR that dropped the key, or a PR that drops a key from `en.json`
after a translation PR added it to a language the dropping PR did not know. On 2026-11-03 zh-Hans
(#1284) landed right after #1285 had dropped three `sessions.*` keys, and #1296 removed them again. A
clean `git merge-tree` does not show this.

**Workaround:** until CI checks a PR's merge with the current main, a PR that changes `web/i18n/en.json`
or a language file is checked against the main it merges into, just before the merge; `CONTRIBUTING.md`
("Before merging a change to the web catalogs") says how. The PR's green CI ran against the older main,
so it does not count. Keeping a dropped key in the languages does not help either: a key English lacks
is a finding by design.

**Rejected alternatives:**
- Finding out-of-date keys from `git log`: shallow CI clones have no history, and a reformat of the
  file would read as new translations.
- A command that marks a language as translated: one run after any edit would mark every key current.

## What counts as prose: sentences by shape wherever they stand, a lone word only by where it stands

**Id:** c14e7b90-3a6d-4f28-8e15-7d2a60b9f3c1
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** review findings on card tsk-ya56x9gx986r, 2026-11-02: `"Pick a conversation."` and `" reads what you write here…"` were not counted, so a baseline of zero would have proved nothing
**Revisit when:** the baseline reaches zero, or a false positive cannot be worded around

`prose()` in `tools/check.py` counts a literal of three words or more that starts with a capital or ends
like a sentence wherever it stands; no context hides one. Other literals are excluded by shape (class
lists, paths, selectors) and by the code before them (`class:`, `===`, `querySelector(`). A lone lowercase
word counts only as a piece of a sentence (`"to "`) or where a person reads it (`textContent =`, the content
of `h()`, `title:`). Others stay with the reviewer: `"online"` beside a variable cannot be told from a key.
A `#` comment with words in it counts whatever the line is, since a person reads it in the generated file.

`prose()` stays an approximation on purpose: a lone word in an `h()` call over several lines is not seen,
because `before` holds one line. The ratchet shows the direction. The proof that nothing is left untranslated
is the run with a pseudo catalog, so further single cases are not chased here.

**Rejected alternatives:**
- Counting every lone word: thousands of keys and values, and the ratchet would mean nothing.
- Shape alone: `"Text (Markdown)"` and `", in "` read like code to it, `"reply primary"` like words.
- A browser run that collects what is on screen: it sees only the views a run opens.

## A refusal is translated by code in `ApiError`; in English the hub's message stays

**Id:** 8b52e0d4-1f7a-4c69-b3d8-60a7c9e1f24d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-ya56x9gx986r, 2026-11-01; docs/api.md §6.2 (the API stays in English, a client translates by `code` and `details`); about 795 places in the hub raise an error, with views showing `err.message` in about 50 lines
**Revisit when:** a language's readers report refusals too vague to act on, or the hub's messages move to a catalog of their own

`ApiError` asks `M.errorWords` once, so no view changes. The catalog has one sentence per code of §1.3
and a few for `details.reason`: it says the kind of refusal. The hub's message says the case, naming a
card or a limit, and a translation loses that. So English readers keep the hub's message, and only a
translated language gets the kind. A `details.reason` the catalog knows comes before the code, since
under `forbidden` it says more. Each code is written out as `M.tOwn("error.<code>")`, because
`tools/check.py` reads keys only as literals.

**Rejected alternatives:**
- Translating the roughly 795 messages: a sentence per place in the hub, in ten languages, with values
  inside them; the contract already says a client goes by `code`.
- Using the catalog's sentence in English too: every English reader would lose the specifics for the
  sake of one rule.
- A map in every view: 50 places to keep in step.
- One computed key per code: the key check could not see it, and every `error.*` key would read as unused.

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
or "an" in code, which only English has. In "X of Y" the plural form
follows the total, Y ("1 of 3 instances active"), as English writes it.
Rejected: the form of X, which read "1 of 3 instance active". A word of
the contract that more than one page shows (a card's label, status,
contract state, a pull request's state, a project's state) has one set
in `M.dom.word(set, value)` in `dom.js`; a value the hub adds later reads
as it comes. Rejected: a map per file, which drifted (the board said a
pull request's state with the release editor's keys). Facts
put side by side with a middle dot between them are allowed where each
is a whole text of its own ("3 waiting for approval · 1 registered in
the last hour"); what stays rejected is a sentence made of pieces. A language offered for choice
is named in itself ("English", "Deutsch"), never through the catalog: a
reader looks for their own language's name, not its name in the
language shown now. Still the hub's words: an
organisation's roles (`owner`, `admin`, `member`) in its sentences and
options, until a second language gives them keys. A count said with a word ("3 in
progress" in the board bar's name, "2 urgent") is one key per word with
`{count}`, not the label lowercased after a number. A key that counts
has its plural forms even where English writes them alike ("Earlier
joins ({count}): …", "{count} urgent"): another language may not, and the
form chosen by `Intl.PluralRules` is there to be translated. Two counts
in one sentence (Why's "1 error, 2 warnings") are a plural key each inside
a frame key, since each may be one or many on its own and a count the
export does not carry reads "—" with no plural rule. Rejected: one
sentence with two numbers, which no single `count` can choose a form
for. A key per value also lets a
value read in its own words ("you work in ops", not "you are an ops").
Not in the catalog: the runner's starter configuration
(`runners.js`), a file the runner reads and `tools/starter_configs.py`
checks as written, with commands and product names. An element's id or
a key that code matches never comes from a translated label (the admin
area's sections are keyed by a fixed word, `admin-users` in every
language), since it would change with the language. The board's column
names are one set of keys (`cards.column.*`) for the board and the
overview: the board keeps its columns as `[status, name]` pairs, the name
a getter on index 1, because `board.js` reads them as pairs; the
overview a getter per status. Rejected: a second set for the overview,
the same words twice for a translator. A member's page (its Cards tab)
names a card's status with those names too (`M.boardEdit.columnName`),
so a status has one key and renaming a column renames it everywhere.
Rejected: `memberpage.status.*`, a second translation that could drift
from the board's. A refusal a view has no words for reads as
`{field}: {reason}` from one key (`members.refused.unknown`), the
field's underscores as spaces and the hub's reason as it comes: the
sentence's shape is the catalog's, while the two values stay the hub's.
Rejected: the English glued together in code, which no translation
reaches. A text the
dashboard writes into the hub for the reader (the title of a chat the
Lead button makes) is taken from the catalog in the writer's language
and stays as written, as a title they typed would: the hub keeps no
language beside it, the other participants read it as it is, and the
chat is found again by its participants, never by its title; its
maker may rename it (§9.2). Rejected: a chat without a title (the
hub allows one), named from its participants when read: every list
that shows the chat would need that naming, and the participants alone
do not say what the chat is for. A failure is one
sentence with `{reason}` where the hub's words go ("Not saved:
{reason}"): `status.fail(sentence, err)` fills it through
`M.reasonIn`, so a language may put the reason first or in the middle.
Text before an element (an inbox entry's label, a diff line's "added:",
the list of what blocks a release) has its own placeholder (`{entry}`,
`{line}`, `{reasons}`) filled with that element by `M.tn`. A failure
with other values is handed over as a function of the reason,
`(reason) => M.t(key, { name, reason })`, so its text is filled once:
a value that reads "{reason}" (a file's name) stays as it is. A failure
shown outside a status line is filled where it is shown
(`M.t(key, { reason })`). `make check` fails on an English text that
ends in ": ", on a key handed to `status.fail` without `{reason}`, and
on a text put into an element, joined with `+` or written to
`textContent` with a placeholder left unfilled, a placeholder counting
as filled only where the values' object literal has a property of that
name. It does not read values from a variable or a spread, nor follow a
text kept in a variable (tsk-0zbms0wwqhmm, #1498). Rejected: the
reason glued after the sentence in code, which fixed its place for
every language; filling `{reason}` in the finished text for every
failure, which filled it again inside a value.

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

## One renderer draws every text people and agents write, its stored mentions linked where they stand

**Id:** 4315382f-022b-47f2-b23b-b4eeccbdb315
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request that formatting is the same in the chat and the inbox, the copy button included, relayed by the coordinator on the card tsk-8n1p6h3zypwp, 2026-10-31; docs/api.md §8.6 (stored mentions by code-point offset)
**See:** rendering.md#chat-messages-are-markdown-drawn-as-dom-nodes-by-a-small-renderer-of-our-own-never-an-html-producing-library — 854c8122-770c-4c80-be9f-0ce9c90c0d2e — as of 2026-10-31
**Revisit when:** a text needs Markdown inside an interactive control, or the hub stores mentions in a form other than offsets

`js/markdown.js` draws the texts of:
- chats and project messages;
- a request's summary, what was tried, its options' details and its
  answer;
- a card's description and notes, and a report's summary.

All of them get the same code with its copy, links and ids. The mentions
the hub stored for a text are taken in where they stand
(`M.dom.mentionSpans`, the same check as before: offsets in code points,
the text there is the handle). They are marked as private-use
placeholders that no Markdown rule reads, drawn as member links in text
and restored as written inside code, a link's label and address and a
fence's info string; a mention the hub stored inside a link stays the
link's text, never a member link inside it. `M.dom.withMentions`, the inbox's
and the board's own plain-text path, is gone. A project message's
separate line of mentions is gone as well, because the mentions are now
links in its text. A request's title stays plain text: it is the label
of the entry's button, which can hold neither a link nor a copy control.
Its ids are offered beside it, as before (3274d199).

**Reason:** two ways of drawing the same kind of text drifted. The
inbox showed code as text that could not be copied with one click,
while the chat could. Placeholders keep the stored offsets valid against
the source while Markdown rewrites it, so a mention is never re-detected
from what someone typed.

**Rejected alternatives:**
- Linking any `@handle` the renderer finds: a typed name that the hub
  did not store as a mention would become a link (§8.6).
- Drawing a request's title as Markdown inside its button: a link or a
  copy control inside a button is not operable.

## A field's label and control share one layout class; smoke fails on any label that runs inline

**Id:** f8cb056b-9e0c-4729-bc97-c73341204bc0
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the registration form on prod, where labels ran inline with their fields (tsk-egx8xpcrz5z2, #939); the audit of all forms in #939's reviews and the card tsk-jpaqk8m7j52v (one shared rule, and a check so this kind of bug cannot come back); the dashboard's implementation, 2026-10-31
**Revisit when:** the dashboard gets a real browser layout check in smoke, or the jour fixe forms get their layout (then their exemption goes)

A wrapper that holds a label and its control (and a hint or an error)
carries the class `field-stack`: one column, the label above the control.
One rule for every such wrapper, whatever else it is called. Smoke walks
every page it shows, before leaving it and after arriving. It fails on
any label with `for` whose control sits in the same parent when the CSS
lays that parent out neither as grid nor as flex. A checkbox or a radio
beside its label is meant, and so is skipped. A field's error is a
`field-error`, which takes no space while empty; a box-shaped `.error`
that is empty takes none either (`.error:empty { display: none; }`, for
every such box rather than one by one, since the empty box on the
account page came from one that missed its own rule). The jour fixe settings and
action page (`jf-`, `jfa-`), with another implementer, are named
exemptions until their forms get a layout.

**Reason:** a label and an input are inline by default, so a wrapper
without a rule runs them together, and nothing failed when one was
missing: the registration form shipped that way, and an audit then found
six more. A shared class makes the right layout the easy one, and a check
on what smoke renders finds the next one before a person does.

**Rejected alternative:** six rules, one per wrapper, which the next
wrapper would miss in the same way. A check that every wrapper class has
a rule, which needs a list of wrapper classes to keep up to date: the
walk over rendered pages needs none. The check reads a rule in its
context (a descendant selector counts only under its ancestor) and leaves
out rules inside `@media` and CSS comments: a layout that holds at some
widths only is no layout for the label.

## A size is handed to the catalog as a finished string; each role and trust token has its own sentence

**Id:** 3ffde266-1d35-4e6a-8ce3-516e13c620e7
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the reviews of #1144, which moved `attachments.js` and `trust.js` into the catalog, 2026-11-02
**Revisit when:** a second language is added, or a token's sentence needs a role's label rather than its slug

A file size in `attachments.js` passes `M.t` a string that `M.fmt.number`
has already formatted, without grouping and with the digits the size
calls for. `trust.js` has a key per `role:` or `trust:` token
(`trust.every.<trust>`, `trust.every.role.<role>`); a token the web does
not know, such as a project's own role, falls back to the neutral
`trust.every.custom`, with its slug as the value.

**Reason:** `M.t` would format a number itself, with grouping, and
`1023 B` would become `1,023 B`. "Every admin" may need a different form
of "every" or of the noun in another language, so each token gets a whole
sentence of its own.

**Rejected alternative:** `toFixed`, which writes the digits but not the
reader's decimal separator. One sentence `every {who}` with the word put in,
which is a sentence from pieces.

## The proof that the texts are in the catalog

**Id:** ce9ba9bb-087c-44bd-b1af-3a697a7727d3
**Type:** decision
**Status:** superseded
**Superseded by:** 8d1bbe07-94c0-4071-99d5-3d8f342a07a2
**Evidence:** inferred
**Source:** agreement with the lead on card tsk-ya56x9gx986r, 2026-11-02
**Revisit when:** the report is empty and `--strict` is on, or a page's texts come only after a click often enough to hide many

`tools/pseudo_run.py` walks the routes of `tools/smoke.js` in a real browser over the fixtures, with a pseudo catalog,
and reports what carries no mark. `prose()` estimates from the source; this shows what a person actually sees. It runs
as a report while the texts move to the catalog and turns strict with the last language. It does not replace reviewing
a translation, and what only a click shows is not walked.

**Rejected alternatives:**
- The run inside `tools/e2e.py` against a hub: its steps look for English words, so a pseudo language fails them all,
  and it reaches far fewer pages than the fixtures do.
- A pseudo language in the repository's catalogs: it would be offered to people and need a marking to keep it out.
- The routes in a list of its own: it would fall behind; those of the smoke test are already kept up.

## The pseudo run is strict; `translate="no"` marks what stays as it is

**Id:** 8d1bbe07-94c0-4071-99d5-3d8f342a07a2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-33ze4aznv5qj from the lead, 2026-11-02
**Revisit when:** a page's texts come only after a click often enough to hide many, or fixtures grow so that judging data by their strings lets catalog wording through

`tools/pseudo_run.py --strict` runs in CI's `web-e2e` now, not only with the last language: today's findings were
cleared, and each language's pull request and each new view would otherwise bring new ones back unseen. What a page
shows on purpose as it is (an example address, a language's own name on its tab, a technical reason from the browser)
carries `translate="no"`, which the run skips together with `aria-hidden` decoration. The attribute is HTML's own word
for it, and browsers' page translation leaves those parts alone too.

What the fixtures say is data: their JSON and the answers `js/api.js` writes itself, minus any literal a view writes as
well and minus the catalog's texts. Prose under an enum's key (a decision's reason, a release's scope) is data, a bare
enum value is not, so a raw state still counts. A fixture's text also counts in the pieces a page splits it into at a
code span or a mention, raw with their stops, so `Keep it;` is data and the button `Keep it` is not. Dates, commits,
handles with instances, device codes, mail addresses, domains and media types are no words.

Two fixture names are also catalog texts, `Reviewer` (`role.reviewer`) and `OZ Team` (`orgs.new.name_placeholder`).
Taking the catalog out would drop them from the data, and every page showing those agents would be reported, so
`FIXTURE_NAMES` in `tools/pseudo_run.py` puts them back (a workaround). The price: a view that writes `Reviewer` itself
instead of `role.reviewer` is not reported on any page.

**Rejected alternatives:**
- Renaming the two fixtures so that no name is a catalog word: `tools/smoke.js` matches `Reviewer` exactly some thirty
  times (member rows, conversation order, notices), a change out of proportion to one exception.
- An allowlist of the texts the run should accept: it would grow with every fixture and hide a real finding in it.
- Any two words inside a fixture's prose as data: 18 catalog texts such as `in progress` and `not valid` occur in some
  fixture sentence and would never be reported.
- A class of our own for "stays as it is": `translate="no"` already means that, also to a browser's translator.

## One word per thing in the translations

**Id:** fc2e6592-2711-447a-978c-75a9ccce1e0a
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** reviews of the German catalog on card tsk-8vzj9gnhed0e, 2026-11-02
**Revisit when:** a language's speakers find a word of `web/i18n/glossary.md` wrong, or the maintainer wants neutral names for trust levels

`web/i18n/glossary.md` holds one word per thing for all ten languages, since a change later touches each of them. A
takeover is `Ablösung`, because a claim is already `Übernahme` and the two are different acts: a takeover carries a right
to object. A claim's release is `zurückgeben`, because a human's go is already `Freigabe`. An arbiter is `Schiedsinstanz`,
a role someone holds, like the other languages' word. A trust level keeps its one name even where a neutral form exists,
so that a level reads the same everywhere; the words around it stay neutral where they can.
A report of abuse is resolved with `erledigen` on every key of its page, because `bearbeiten` is already the word for Edit and
reads as editing.
A release keeps its own word apart from a version where a language has both: `A release with this version already exists`
names the two together, and legal pages and older frames already use `version` for a saved text. The German row fixes one gender, `das Release`, because a half-changed catalog had `ein anderer Release` next to
`ein Release`; why the neuter won over `der Release` is not recorded.
Words outside the table follow the same aim. In Spanish, redacting is `suprimir`, deleting is `eliminar` and the button
Remove is `Quitar`: three acts with three words, so a deletion text cannot be read as hiding or as removing from a list.
"Reports to" is `informa a` on every key; the anglicism `reporta a` appeared on half of them. A waiting text whose verb is
reflexive takes the noun, `Incorporación en curso…` for Joining, because a Spanish reflexive gerund needs a person.
A pull request is masculine in Spanish on every key, its states too, since they are put into sentences about it. The duplicate check in `web/tools/check.py` treats a comma list in a cell as forms of one
word, and `GLOSSARY_FORMS_OF_ONE` names rows that are one thing: `user` and `users`, a person and a human, `join` as
noun and verb.
In Portuguese, a join is `ingresso` (its states masculine to match), signing in is `acesso` as a noun and `entrar` as a
verb, two-factor sign-in included, and `entrada` keeps its own senses, an entry (of memory, of Keep the Why) and the
inbox (`caixa de entrada`), so a join or a sign-in never shares its word. A custom role is `todos com a função {role}`,
because a role's name cannot be put in the plural and the role may be an agent's. A project's launch is `estreia`, since
`lançamento` is its release. Step-up subjects are infinitives, as in Spanish, because `stepup.*.hint` puts them first in
a sentence (`{what} exige …`). Legal pages are `páginas jurídicas`: `legal` in Brazilian Portuguese also means "cool".
In Dutch, taking a member out of a project or an organisation is `weghalen` on every key, because `verwijderen` is
deleting and an agent that is taken out is not deleted; buttons that take a value, a link or a picture out of a list
keep the usual `Verwijderen`. An entry (of memory, of Keep the Why) is `item`, a join `deelname`, a sign-in `inloggen`
(two-factor sign-in `inloggen met tweede factor`), three words for three things. Step-up subjects are infinitives
(`De landingspagina opslaan`), not `Het opslaan van …`, so that every one reads alike before `stepup.*.hint`.
In Japanese, legal pages are `法務ページ` on every key, the name the page and its menu entry carry; `法的情報` stays the
footer's heading. A custom role is `ロール {role} を持つ全員` wherever it stands, and a trust level in a sentence is
`信頼レベル` with the level's own word (`オーナー`, `管理者`), never the raw `owner` or `admin`. A dormant instance is
`休眠中`; `休止中` is an agent at rest (`availability.dormant`).
In Korean, labels and messages are 해요체 and legal and security texts 합니다, as the glossary says. A custom
role is `{role} 역할을 가진 모든 사람` wherever it stands, and a built-in role keeps its lowercase word, as in
Japanese (`coder 전원`). Redacting is `제거` on every key, the word on the button, in the portal and in the hub's mails
alike. A step-up's subject is a noun phrase (`2단계 인증 해제`, `계정 삭제`), so that every one reads alike.
The bell's texts about security alerts (`bell.security_hint`, `bell.mark_all.ask`, `bell.skipped.*`) are 해요체 like
the rest of the bell, a message in a list, while `sessions.*` stays 합니다 as the security page. Confirming a sign-in is
`확인` on every key; marking an alert read is `읽음` with `표시` and never `확인`: `읽음 표시` on the buttons of the bell
and the sessions page (`bell.mark_read`, `sessions.mark_read`), `읽음으로 표시` in sentences and on `waiting.*`. This
was me is `본인입니다` as on `sessions.this_was_me`, so that marking read never reads as confirming (#1301, 2026-11-03).
An imprint is `운영자 정보` everywhere, the word the hub's footer had first and the one Japanese uses (`運営者情報`); the
terms are `이용약관`, without a space. Changing a password and resetting someone's second factor (`password.*`,
`users.reset.*`) are security texts and so 합니다, like `security.*` and the hub's reset mail, and the hints on deleting
a profile are 합니다 like those on deleting the account. A particle after a placeholder whose value may end in a vowel
or a consonant gives both forms (`이(가)`, `(으)로`, `은(는)`, `와(과)`). The copula has no such pair: `(이)에요` reads as
`에요` after a vowel, where `예요` is right, so no copula follows such a placeholder; the sentence takes a colon or is
rephrased (`{name}의 역할이 바뀌었어요: {role}`).
A confirmation question (`…할까요?`) and the sentence after it share one register, 해요, also on a legal or security
page: a dialog is a message to the person at the screen, not the legal or security text itself, and one dialog never
switches mid-way; 합니다 after a 해요 question was rejected because the dialog then mixes both.
In Simplified Chinese the reader is `你`, as the glossary says. Redacting is `移除` on every key, the word on the
button, in the portal and in the hub's mails alike (`reports.action.remove.hint`, `mail_links.delete_keeps`), never
`抹除`. A review's Approve is `通过`, because a human's go is `批准`, and a project's launch is `推出`, because a
deploy is `上线`. The role proxy and the Meat Proxy stay two things: `Meat Proxy` keeps its English name. A role in
a sentence is `所有 {role}` with the role's English word, as in `trust.every.role.*`. A dormant instance is `休眠`,
as on every key that names one, and a maintenance window is `维护时段`.
The imprint is `运营者信息` on every key that names it, the page's own title (`frame.imprint`), the
registration's link and the portal's legal settings alike, as in Japanese and Korean. A public page shows you as
online while you are (`在你在线时显示你在线`), not when you were (`何时在线` reads as a history).

**Rejected alternatives:**
- `Übernahme` for both claim and takeover: an error then says a card "needs a takeover" next to "nobody has claimed it".
- `Schlichtung` for arbiter: a procedure, and it reads badly before a name.
- `version`, `versión`, `versão` for a release: one word for two things in `error.version_exists`.
- `bearbeiten` for resolving a report: a half-changed page showed `Erledigen` next to `Wird bearbeitet …`.
- `der Release`: in use as well; one gender was the point.
- `eliminar` for redacting in Spanish: it is already the word for deleting an account or a project.
- `Uniéndote…` and `Uniéndose…` for Joining: one addresses the reader, the other reads as the formal address; the glossary wants a neutral waiting text.
- `entrada` for a join or a sign-in in Portuguese: it is already an entry and the inbox, and reads as a door, not an act.
- A neutral form for `Besitzer` in the table: it would make the level's name differ between labels and sentences.
- `法律声明` for the imprint in Simplified Chinese: it reads as a disclaimer and gave one page two names.


## Where the glossary contradicted itself or the catalogs

**Id:** f09998b6-128b-4430-b8d0-fd793d674b4e
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** jour fixe proposal t4.s4 of 2026-11-02, adopted as card tsk-jasa8bynb8x3; findings of the reviews of #1156, #1167, #1169 and #1174
**Revisit when:** a language's speakers find `le fil` or `puesta en marcha` wrong, or a role in `role.*` is renamed to a position's word

Reviewers and translators guessed anew at each language where the glossary disagreed with itself or with the catalogs.
Each case is settled once:

- **Role words and positions.** The rule said role words stay English while the table translates `lead` and `arbiter`.
  Role words are the names in `role.*` (`coder`, `reviewer`, `ops`, …), labels a person picks from a list; a position in
  a team or a contract (`lead`, `arbiter`, `owner`) is said in a sentence and takes its row.
- **Launch and release.** `state.launch` was `Lanzamiento` in Spanish, the table's word for a release, so the board
  named two states alike. A row for the project's state: Spanish `puesta en marcha`, Portuguese `estreia` (its release
  is already `lançamento`); the other languages had distinct words already. The duplicate check of
  `web/tools/check.py` now guards the pair.
- **Ticker and feed in French.** `le fil` stood for the ticker and, in `projectmessage.intro`, for the project's message
  feed. The ticker keeps `fil d'actualité`, `le fil` in a sentence once it is named; the feed is `flux`, with a row of
  its own.
- **Trust in Spanish** read `Confianza` in labels and `nivel de confianza` in sentences; now the row's word everywhere,
  as in German and French.
- **Operator in German** read `Betrieb` twice beside `Betreiber`; now `Betreiber`.

**Rejected alternatives:**
- Translating role words like positions: they are picked from a list and appear in commands such as `role:coder`, where
  a translated label would not match what an agent types.
- Spanish `lanzamiento` for launch and another word for release: the release row was settled in #1167 and eight
  catalogs build on it.
- French `fil d'actualité` in full in every sentence: nine sentences grow long for no gain once `le fil` means the
  ticker alone.

## `make check` holds every translation to the glossary's fixed terms and form of address

**Id:** 7d49c1e3-32a6-4a9e-af9e-c385ee719ee0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-47tbmmmemf6x and the reviews of PR #1457, 2026-11-07; findings of the reviews of #1451 (a translated `harness`, Portuguese `tu` forms)
**Revisit when:** the address table of `web/i18n/glossary.md` changes its shape, informal French possessives (`ton`, `ta`) appear in a catalog, or Chinese gets a check for `您`

See: rendering.md#one-word-per-thing-in-the-translations — fc2e6592-2711-447a-978c-75a9ccce1e0a — as of 2026-11-07

Reviews kept finding the same two slips by hand: a term the glossary keeps as it is came back translated, and a text
used the other form of address than the one the glossary names. `web/tools/check.py` now reads both rules from
`glossary.md` itself and checks every catalog and the hub's mail words: a term its Words table keeps `unchanged` in
every language must stay in a text whose English holds it, and a text uses no word of the other address
(`GLOSSARY_OTHER_ADDRESS`). Code spans and placeholders are taken out first, and a placeholder reads as a number, so
`{harness}` is no harness and Dutch `{count} u` stays hours. German `Sie` and `Ihr…` count only inside a sentence. An
address in the table that the check does not know is itself a finding, so the table cannot change unseen.

Chinese is not checked, and no reason was weighed for that: the check grouped it with Japanese and Korean when it was
written, as if its address were a register too. It is not: the glossary names `你`, and the other address is the
single character `您`, which a pattern finds; neither Chinese catalog holds `您` (found in the delta review of #1457).

**Rejected alternatives:**
- Checking `resume` with the other fixed terms: the glossary translates it as an ordinary verb, so the check would flag
  correct sentences; it stays a reviewer's call (`GLOSSARY_NOT_CHECKED`).
- Flagging French `ton` beside `tu`, `toi` and `tes`: `ton` is also a noun, and the French catalog uses it so
  (« Le ton, la longueur … »), which the check would flag. `ta` and `te` were dropped together with `ton`, with no
  reason of their own; neither occurs in a French catalog today.
- A word list for Japanese and Korean: their address is a register (です・ます, 해요체), not a set of words a pattern
  can find; nothing is checked there and reviewers keep it.
- Leaving both rules to review alone: the same findings came back on #1451 after the glossary named them.

## A list drawn as a grid holds its rows in one column of `minmax(0, 1fr)`, so a long line cannot widen it

**Id:** af756909-d3b0-4484-af3f-f88c41014ac4
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-6bn80bppb5e5 (a request with a long code line and long card links pushed the inbox of all projects past the window, every collapsed row with it); web/css/app.css `.entries`, `.entries-box`, `.card-note-list`, `.card-family`, `.md`, `.about`, `.card-links li`; the e2e step `wide_lines_step`; the lead's approval of the plan, 2026-11-04
**Revisit when:** a list of written text is laid out as something other than a grid, or a Markdown code block wraps its lines instead of scrolling

The inbox's lists (`.entries`, `.entries-box`) and the card panel's
lists and grids (`.card-note-list`, `.card-history-list`, `.card-links`,
`.card-family`, `.card-family-form`) set
`grid-template-columns: minmax(0, 1fr)`. A code block in a request or a
note keeps its lines and scrolls inside itself (`.md-code`,
`overflow-x: auto`), the text around it wraps, long links too
(`overflow-wrap: anywhere` on every text drawn as Markdown: `.md` in
the dashboard's views, `.about` on a visitor's pages; and on a card's
links, `.card-links li`, where a link without a label shows its
URL; a code block is `pre` and keeps its lines), and the row is as wide
as its list.

**Reason:** a grid without columns of its own gives its rows one implicit
`auto` column, and a grid item's minimum width is its content's: the
longest line of a code block that does not wrap. One open request with a
600-character line in a code block made the page 4420 px wide in a
1280 px window, and every other row of the list the same width. In the
card panel the same note made the whole panel scroll sideways, not its
code block; the note's long links did too, since `.md` had no
`overflow-wrap` of its own, and only some rows gave it one
(`.entry-body`, the chat's `.msg`). A visitor's card page with the same
links was 539 px wide in a 390 px window (`.about`). In the project's
messages, with no panel around them, those links made the page 579 px
wide in a 390 px window. A card link of 300 characters made the card
panel 2162 px wide inside its 510, and a long title in the family's
select 394 inside 364 on a phone. A column of
`minmax(0, 1fr)` gives the rows the list's width, whatever they hold. The
chat was not affected: its messages already have `min-width: 0`.

**Rejected alternative:** `min-width: 0` on every row (`.entry`, each
note): it works only where it is set, and the next list of written text
would have to remember it. `overflow-wrap` on each list's rows instead
of on `.md`: the same, for every view that shows written text.
Wrapping code lines (`white-space: pre-wrap` in `.md-code`): a shell
line or a path broken across lines reads as several, and the block's
scrolling stays as it was.

## Every absolute time is formatted in the account's time zone by one helper, and in the browser's while none is set

**Id:** 89d0260c-1827-40a7-b67d-84c91568772a
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the owner's decision that a human sets their time zone in Account → Settings and sees times in it (message seq 94723), the approved plan on card tsk-j8s6n725a06r, 2026-11-08; docs/api.md §5.1; `js/i18n.js` (`when`, `M.fmt.day`, `toWall`, `fromWall`)
**See:** https://github.com/oliver-zehentleitner/maity — c9d8b583-94c6-4599-90a6-325e1c03c984 — as of 2026-11-08
**Revisit when:** the dashboard shows a time that is not an instant (a date without a time, a wall time of a schedule), or the hub starts rendering times itself

`M.fmt` formats every absolute time with `timeZone` set to the account's zone, which `M.api`
takes from each `GET /me` (`member.timezone`) that passed the session check and set out after the
last saved change of the zone, and from the settings `PATCH` that saves it; while that is `null`,
or a name the browser's Intl does not know, it is the browser's zone. A session that ends
(signing out, expiry, a 401 on the newest session check of the current session) drops it, so the next person in the tab does
not see the last account's zone. The places that worked on the browser's local clock
(`getDate`, `toDateString`, `toLocaleDateString`) go through the same helper: chat's day
separators compare `M.fmt.day`, the maintenance banner's "same day" test too, and the
`datetime-local` fields (the instance admin's maintenance window, the owner's absence) read and
write the account's zone with `M.fmt.toWall` / `fromWall`
(a time a clock change skips moves forward by the gap's length, so 02:30 in a one-hour gap is
03:30; one it repeats is the first). Relative
times ("5 min ago") do not use the zone. Timestamps in the API stay UTC.

**Reason:** the owner decided that every time shown follows the zone the human set (confirmed).
One helper is the only way that stays true: a view that formats on its own would show the
browser's zone beside the account's, and a datetime-local field in the browser's zone would let
an admin enter a window in another zone than the one it is then shown in. Taking the zone from
`/me` costs no request, since every page reads it before the first view.

**Rejected alternatives:** reading `GET /me/notification-settings` at load: a second request on
every page for one value `/me` can carry. Rendering times on the hub: the contract keeps UTC in the
API and leaves display to the dashboard. Keeping the browser's local clock for day boundaries
while formatting in the account's zone: a message at 23:50 in the account's zone could then sit
under the next day's separator.
