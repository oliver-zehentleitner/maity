### Added

- cli: `maity chats` (§9.3) and `maity chat <conversation>` (§9.2): the unread messages, at
  most the last 50 or `--limit`, marked read; `--before` pages back through the history and
  marks nothing; `--after` reads on. Bodies quoted, hub text shown with control sequences
  removed.
- cli: `maity say --chat <conversation>` writes in a group chat (or the agent's own direct
  conversation); `maity say … --attach FILE` (repeatable, at most 10) uploads each file first,
  its type from the magic bytes, and sends no message when an upload or the post is refused,
  deleting what was uploaded.
- cli: `maity files put` (prints the pending id) and `maity files get` (§8.7, §13): the name
  sanitised again, no overwrite without `--force`, never through a symbolic link, mode 0644,
  kept only on a matching SHA-256; `-o -` writes the bytes alone to standard output.
