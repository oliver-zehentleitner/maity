### Added

- hub: the change ticker, third part (docs/api.md §17.4): the forge webhook
  (`POST /api/v1/projects/{slug}/forge/webhook`), signed with a secret the hub issues
  (`GET …/forge/webhook`, `POST`/`DELETE …/forge/webhook/secret`, `forge_webhook_changed`), its
  deliveries limited and checked before the body is read and only ever a trigger for the probe;
  automatic deploys from a successful `deployment_status`, listed for everyone, waking no one
- hub: `MAITY_SECRET_KEY`, the instance key for secrets stored at rest (AES-256-GCM,
  `maity_hub.secretbox`); the new dependency `cryptography` 50

### Changed

- hub: `event.subject_id` holds up to 255 characters (migration 0017): an automatic deploy's
  subject is `<environment>@<sha>`, longer than an id
