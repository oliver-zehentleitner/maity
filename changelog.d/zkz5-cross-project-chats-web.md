### Added

- web: cross-project group chats on Chats (`/chats/cross/new` and
  `/chats/cross/<id>`, §9.5), ported from #1422 onto main. The owner
  creates a room of their own agents, reads and writes it, and manages who
  is in it. A mention is the only wake. The chat has no files, no
  meat-proxy switch, no per-participant wake, no verdicts and no agent
  firewall lines. It has the full-screen button, and its people, mentions
  and instances link to a project's Team view. Reporting a message here is
  not part of this change.
