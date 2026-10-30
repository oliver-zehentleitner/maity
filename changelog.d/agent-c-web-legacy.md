### Removed

- web: the runner pairing form no longer retries without `attach` for a hub before §15.4; the
  attachments no longer read a 404 or 405 as a hub without them (only `409
  attachments_not_configured` is "off"); the fixture hub and fixtures no longer carry
  `legacy_slug`, which the hub dropped.
- web e2e: the fallbacks for older hubs: without attachments or with them off, without
  notifications, the session list, the chat list across projects, group chats, the ticker, the
  overview, runners, the card move or the avatar upload; the e2e hub serves all of them.
