### Added

- hub: landing V3 stage 1 (docs/api.md §16.7). The landing page has the designer's look: a dark hero with the rings as inline SVG, the call-to-action band with its loader, a theme switch (a `hidden` button in the page's language that the script shows), and its own stylesheet and nine self-hosted `woff2` fonts (Space Grotesk, Inter, JetBrains Mono, OFL texts beside them) under `/assets/landing/`, served from the hub package with `?v=<digest>` (`immutable` under the right digest, `no-cache` otherwise) and `landing.js` when the hub has one, `defer`. The page reads completely without them: every section shows its end state, the FAQ is `<details>`, a counter is `<span data-lp-count>`. Two new section types: `demo` (a terminal of 1–8 `cmd`/`out`/`note` lines, an optional inbox question, exactly three steps) and `opensource` (a title, optional Markdown, 1–3 tiles, 0–4 links), validated with field paths like the others.

### Changed

- hub: the landing page and its preview answer with `default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'` (the legal pages keep theirs), `GET /robots.txt` allows `/assets/landing/` while the landing page is enabled, and the counters' numbers sit in `data-lp-count` elements.
