### Removed

- web: the runner pairing form no longer retries without `attach` for a hub before §15.4, and the
  fixture hub and fixtures no longer carry `legacy_slug`, which the hub dropped.
- web e2e: the fallbacks for a hub without attachments or with them off (the 409 on the pending
  uploads, the pairing note); the e2e hub always runs with an attachment store.
