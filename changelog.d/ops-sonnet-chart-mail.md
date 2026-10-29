### Added

- deploy: the Helm chart wires the mail settings: `mail.signingKeySecret` and `mail.passwordSecret` name existing Secrets
  (`MAITY_MAIL_SIGNING_KEY`, `MAITY_SMTP_PASSWORD`), `mail.host`, `port`, `tls`, `username`, `from` and `replyTo` set the rest
  (`MAITY_SMTP_*`). Nothing is rendered without a value.

### Changed

- docs: §16.2 of `docs/api.md` names the chart values as they are (`mail.passwordSecret`, `mail.signingKeySecret`, `mail.host` and the rest),
  says the instance key comes through `extraEnv`, and that moving the variables from `extraEnv` into `mail.*` drops them from `extraEnv` in the same upgrade.
