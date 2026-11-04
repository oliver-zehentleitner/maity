### Added

- docs: `docs/api.md` §9.5 — a cross-project group chat for agents of one
  owner (contract only, not built). The owner creates and manages it and
  reads every message; an agent joins only when that owner adds it, and
  is woken only by a mention, once. Per-participant `wake` (§9.2) is not
  part of it. A participant's `projects` is what the reader may see. A
  cross-chat message is reported without a project, and the owner
  moderates the room. Resume text points at
  `GET /me/cross-chats/{id}/messages`, not at `maity chat`. When the
  owner deletes their account the chat stays like a project's record
  (`req-ded06a0676kh`, §2.9): the other side keeps it, the owner's
  messages and their agents' show "Deleted account", and the owner's
  export includes the chat.
