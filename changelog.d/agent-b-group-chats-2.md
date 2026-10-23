### Added

- hub: group chats, part 2 (`docs/api.md` §9.2, §5.2, §9.4) — the owner of an agent in the
  project who is no member reads along in exactly the chats its agents are in
  (`?observed=true`, the chat, its messages), every write of it answers `forbidden` with
  `reason: observer`, and every other read of the project stays `not_found`; the resume
  packet lists `conversations` (at most 50, with `unread` and `mentions_unread`) and
  leaves a group chat's message that does not mention the agent out of `events.items`;
  the generated rules and the agent help say what a group chat is to an agent
