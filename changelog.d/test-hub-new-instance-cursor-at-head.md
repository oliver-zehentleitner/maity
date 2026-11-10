### Changed

- Hub: a new agent instance (the first session of a credential, also after `replaces`) starts its
  event cursor at the project's current head instead of `0`; its first `maity resume` and
  `maity wait --batch` no longer replay the backlog. History stays available with `after=`, and an
  explicit `cursor` in the resume body is still honoured (docs/api.md §5.2, §8.3, §6.17).
