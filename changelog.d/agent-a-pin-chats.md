### Added

- docs/api.md §9.3: a human pins conversations (`PUT`/`DELETE …/conversations/{id}/pin`, at most 20);
  both conversation lists order pinned chats with unread messages first, then unpinned ones with
  unread messages, then quiet pinned ones, then the rest; items carry `pinned`.

### Changed

- docs/api.md §16.7: header links only from shown, enabled sections with `nav_label` (disabled ones
  count for nothing, anchor `#s<index>`); the footer's columns come from existing fields only.
- docs/api.md §5.2, §13: `chat_url` names the agent's member id as the conversation id; `maity join
  --no-resume` prints no chat line.
