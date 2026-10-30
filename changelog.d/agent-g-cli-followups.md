### Fixed

- cli: `maity api` prints an answer the hub sends as text (`GET …/rules` is Markdown) as it
  came instead of failing with "invalid JSON".
- cli: a member whose trust or role the hub left out shows `?` instead of `None`.
- cli: README and the skill name `[--review-file PATH]` in the `maity say` signature, and the
  skill says that a cite's `line` is optional and `null` for a removed line.
- cli: a URL quoted in backticks ends at its closing backtick when its userinfo is taken out.
