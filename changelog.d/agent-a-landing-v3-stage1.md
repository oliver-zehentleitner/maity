### Changed

- docs: the landing page (§16.7) is progressively enhanced: first-party `landing.css`, `landing.js` (≤ 10 KiB, `defer`) and self-hosted fonts under `/assets/landing/`, never needed to read it; its policy allows script, style, fonts and images from the hub only, no connection.
- docs: new landing sections `demo` (terminal lines, an inbox question, three steps) and `opensource`; the FAQ is rendered as `<details>`.
- docs: `robots.txt` allows `/assets/landing/` while the landing page is enabled; `demo.subline`, `demo.inbox.context` and `opensource.markdown` are optional (§16.7).
- docs: `/assets/landing/` is served by the hub from its package (§16.11); `img-src 'self'` only; the theme switch is in the HTML; the demo's inbox item appears after the last line.
