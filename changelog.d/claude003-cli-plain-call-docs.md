### Fixed

- cli: the start prompt of a placed Claude Code agent and the hook's refusal
  say that a `$` is refused only outside single quotes, as the hook already
  decides; `docs/runners.md` says so too and counts a Claude Code older than
  2.1.295 among the sessions without the harness's sandbox.
