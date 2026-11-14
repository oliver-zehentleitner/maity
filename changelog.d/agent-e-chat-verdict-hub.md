### Added

- hub: a human gives a chat message 👍 `agree` or 👎 `disagree`, with an optional sentence on
  👎, one per human and message, changed or taken back at any time
  (`PUT` and `DELETE …/conversations/{id}/messages/{seq}/verdict`, docs/api.md §9.7): the
  owner in a direct chat, a participant or an observer reading along in an open group chat; an
  agent and a bridge are refused with `humans_only`. Every change writes a `chat_verdict` to the
  chat's participants, which wakes only the agent that wrote the message and is in the resume
  packet of that agent alone. It is redacted as a chat message is, without `events:admin`;
  the verdict it set stays and then reads its value without the sentence.
- hub: every chat message carries `verdicts`, the current verdict of each human, oldest first
  (§9.1); a redacted message carries none.
