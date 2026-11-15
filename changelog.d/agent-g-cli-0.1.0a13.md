### Changed

- cli: version 0.1.0a13 for PyPI. The runner installs and updates
  Claude Code and Codex where its configuration says so, from checked
  vendor releases, beside the version in use, with `maity runner tools`
  and `rollback`, the owner's "Update now" and `login_needed` (#1805,
  with the fixes of #1862 and #1863). `maity wait`'s chat read on a
  timeout renews no claim lease (#1856). An antigravity (agy) placement
  gets no command grants, and the runner does not offer agy until it can
  confine agy's `maity` at the OS level (#1859, #1860).
