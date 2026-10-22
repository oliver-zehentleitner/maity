### Changed

- docs/api.md §9.1, §9.2: how `…/messages` shows a redacted message (`body: null`, `mentions: []`,
  `attachments: []`, `redacted: true` as in the list preview, and a `redaction` object with at, by
  and the reason as §8.5 allows; `false`/`null` when not redacted).
- docs/api.md §8.5: a redaction by number may name what it expects (`expect: closed_chat_message`);
  the normal checks run first, then the hub refuses any other event the caller could redact, so a
  mistyped number tombstones nothing and `expect` reveals nothing to a caller who could not redact.
