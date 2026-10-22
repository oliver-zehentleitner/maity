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
(`Maity.dom.safeUrl`); anything else is shown as text. The paste line a
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
