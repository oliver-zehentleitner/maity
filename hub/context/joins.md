# Joins

## The join page's HTML comes from markdown-it-py with raw HTML off

**Id:** 99c3acf7-2d66-4f0a-8a1c-6f97551a9d5b
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the join slice)
**Revisit when:** the join page needs a construct CommonMark with tables cannot express, or markdown-it-py stops being maintained

A browser opening a join URL gets the same document as an agent,
rendered to HTML by `markdown-it-py` in CommonMark mode with tables, raw
HTML disabled, inside a fixed page with a link to the dashboard and no
script or form. Text a human typed (the project name) is escaped for
Markdown before it goes into the template.

**Reason:** the page is the one document of the hub that mixes the
operator's template, values from the join record and text people type;
it must render without letting any of them become markup. markdown-it-py
escapes raw HTML when it is disabled and refuses `javascript:` links,
and it is a small pure-Python dependency.

**Rejected alternatives:**
- A hand-written converter for the few constructs the template uses —
  no dependency, but one more parser whose escaping the hub would own.
- The Markdown inside `<pre>` — safe and trivial, but the page is meant
  for a human who opened the link in a browser, and code blocks and the
  table become unreadable.

## The join page template lives in docs/ and is shipped into the wheel

**Id:** 93300fee-e6a7-442a-a21e-db8f3f1e6f20
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** implementation session, 2026-10-21 (the join slice)

`docs/join-page.md` stays where the CLI's author wrote it, next to the
contract it follows. The wheel carries it as `maity_hub/join-page.md`
(hatch `force-include`); a checkout without a built wheel reads it from
`docs/`, and the image's build context includes that one file.

**Reason:** the template is written against `docs/api.md` §3.2 and
reviewed with it; one copy means the page an agent reads is the page the
contract describes.

**Rejected alternative:** a copy inside the package — no build-time
step, but two files that drift the first time someone edits the one in
`docs/`.
