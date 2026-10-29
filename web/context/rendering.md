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
**Revisit when:** messages need tables, images or nested lists, or another view wants Markdown beyond what the renderer covers

A chat message is drawn as Markdown by `js/markdown.js`: paragraphs
with their line breaks, headings (a line of strong text, not a page
heading), lists (a numbered one keeps its first number; nested lists are
flattened), quotes (nested at most eight deep, deeper shown as written,
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
outside code: the card on the board (`/<owner>/<slug>/tasks/<id>`, a route
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
**Status:** active
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

## A hub whose attachment store is off is treated like a hub without attachments

**Id:** 831e6402-6484-42a6-971a-0cafd0e7ecb4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** implementation session, 2026-10-27 (the contract change #464: without `MAITY_ATTACHMENT_DIR` every attachment call answers `409 attachments_not_configured`); the dashboard's reading of it is the implementer's
**Revisit when:** an operator can switch the store on without reloading the page, or the hub tells the dashboard which parts it has before it asks
**See:** rendering.md#attachments-an-image-is-shown-from-the-hubs-own-path-every-other-file-is-only-ever-a-download-link-and-nothing-is-previewed-before-it-is-sent — 52e88bfb-69a5-4f6d-95e8-a2a3dd8acdd7 — as of 2026-10-27

`web/js/attachments.js` took a `404` or `405` for "this hub has no attachments"
and stopped asking until the page was loaded anew. A hub that has the
routes but no store answers `409` with the code `attachments_not_configured`
to the same calls, and the e2e run counted that as a problem on a page that
does nothing wrong. The same check now covers that code, so the Attach files
part is hidden and the listing of waiting files is not asked for again.

**Reason:** to the person at the page the two hubs are the same: no files can
be sent. The dashboard should not report an operator's choice as a fault.

**Rejected alternative:** switching the store on in the e2e run only: the page
would still treat an unconfigured hub as broken in production.
