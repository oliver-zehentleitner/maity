### Changed

- docs/api.md §9.2: how `…/conversations/{id}/messages` shows a redacted message (`body: null`,
  `redacted: true` as in the list preview, and a `redaction` object with at, by and the reason as
  §8.5 allows; `false`/`null` when not redacted).
- docs/api.md §8.5: a redaction by number may name what it expects (`expect: closed_chat_message`);
  the hub refuses any other event, so a mistyped number tombstones nothing.
