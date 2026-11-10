### Added

- deploy: the Helm chart wires the mail settings: `mail.signingKeySecret` and `mail.passwordSecret` name existing Secrets
  (`MAITY_MAIL_SIGNING_KEY`, `MAITY_SMTP_PASSWORD`), `mail.host`, `port`, `tls`, `username`, `from` and `replyTo` set the rest
  (`MAITY_SMTP_*`). Nothing is rendered without a value.

### Changed

- docs: §16.2 of `docs/api.md` names the chart values as they are (`mail.passwordSecret`, `mail.signingKeySecret`, `mail.host` and the rest),
  says the instance key comes from `secretKey.existingSecret`, and that moving the variables from `extraEnv` into `mail.*` and `secretKey` drops them from `extraEnv` in the same upgrade.

- deploy: the Helm chart takes the instance key from a Secret as well: `secretKey.existingSecret` and `key` (`MAITY_SECRET_KEY`). Nothing is
  rendered without a value; a release that moves the key from `extraEnv` drops it there in the same upgrade.
