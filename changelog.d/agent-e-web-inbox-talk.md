### Changed

- web: the inbox has one free-text field above the reply buttons, always
  writable; every reply and the Talk button send its text along when it holds
  any (`{reply_id, text}`, `{talk: true, text}`). "Neither — let's talk" is now
  "Talk" in every language and is offered only where the human owns the asking
  agent (never for a human asker, a hub-filed request or an unreadable one); a request without replies keeps Send beside it. The
  fixture hub answers as the contract does.
