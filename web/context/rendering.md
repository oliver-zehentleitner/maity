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
