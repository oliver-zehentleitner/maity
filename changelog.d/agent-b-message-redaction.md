### Changed

- hub: `…/conversations/{agent_id}/messages` items carry `redacted` (as the list preview
  does), `redaction: {at, by, reason}` for a redacted message (`null` otherwise) and
  `attachments: []`; the reason by §8.5's chat rule: the direct chat's human party sees
  it, an agent gets `null` (`docs/api.md` §8.5, §9.2)

### Added

- hub: `POST …/events/{seq}/redact` takes `expect: "closed_chat_message"`, and then redacts
  only a message of a closed group chat; anything else it could redact is `invalid`
  (`details.fields.expect: mismatch`) and nothing changes, any other `expect` value, `null`
  included, is `unknown`, and an event it could not redact answers as without `expect`. Until the hub has group chats, that is every event
  (`docs/api.md` §8.5)
