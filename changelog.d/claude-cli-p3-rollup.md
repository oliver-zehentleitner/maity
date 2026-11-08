### Fixed

- cli: `maity memory delete` no longer parses the entry id's shape (ids are
  opaque, docs/api.md §1.1); it refuses only `.`, `..` or an empty id, and an
  id the hub does not have is the hub's `not_found` (tsk-v0m0wbkm3d7j).
- cli: a repository grant rule with a run of spaces is refused with the hint
  to separate the words with single spaces (tsk-v0m0wbkm3d7j).
- cli: the skill says that an escalated takeover is decided by the
  project's admins (§6.19), and the README's list of maity's own git calls
  names the first resume's remote check (tsk-v0m0wbkm3d7j).
