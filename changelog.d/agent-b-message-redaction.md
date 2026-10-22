### Changed

- hub: `…/conversations/{agent_id}/messages` items carry `redacted` (as the list preview
  does) and `redaction: {at, by, reason}` for a redacted message, `null` otherwise; the
  reason only for the human owners and admins and the redactor (`docs/api.md` §8.5, §9.2)

### Added

- hub: `POST …/events/{seq}/redact` takes `expect: "closed_chat_message"`, and then redacts
  only a message of a closed group chat; anything else is `invalid` (`details.fields.expect:
  mismatch`) and nothing changes. Until the hub has group chats, that is every event
  (`docs/api.md` §8.5)
