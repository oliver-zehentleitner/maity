### Added

- hub: group chats in notifications (`docs/api.md` §18.1, §18.2, §9.2) —
  chat and mention items from a group chat for its participants, from
  their current stay on (never an observer, never the writer; a chat the
  human left drops out), titled with the chat's name; the chats' unread
  counts in `counts.chat` and `by_project`; marking an item read moves
  the chat's own mark.
