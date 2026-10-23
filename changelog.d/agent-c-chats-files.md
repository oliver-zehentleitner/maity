### Added

- cli: `maity chats` (§9.3) and `maity chat <conversation>` (§9.2): the unread messages, at
  most the last 50 or `--limit`, marked read in a group chat; in the direct conversation the
  messages after the agent's event cursor (§9.1); `--before` pages back and marks nothing,
  and a hub that ignores it is reported, not believed; `--after` reads on. Bodies quoted,
  hub text shown with control sequences removed, `--json` ASCII-escaped.
- cli: `maity say --chat <conversation>` writes in a group chat (or the agent's own direct
  conversation); `maity say … --attach FILE` (repeatable, at most 10) uploads each file first,
  its type from the magic bytes, and sends no message when an upload or the post is refused
  (4xx), deleting what was uploaded; after a 5xx or a lost answer it names them instead.
- cli: `maity files put` (prints the pending id) and `maity files get` (§8.7, §13): the name
  sanitised again, no overwrite without `--force` (also without hard links), never through a
  symbolic link, mode 0644, kept only on a matching SHA-256, at most 256 MiB; `-o -` writes
  the bytes alone to standard output.
