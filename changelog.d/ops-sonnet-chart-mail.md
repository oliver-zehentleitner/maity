### Added

- deploy: the Helm chart wires the mail settings: `mail.signingKeySecret` and `mail.passwordSecret` name existing Secrets
  (`MAITY_MAIL_SIGNING_KEY`, `MAITY_SMTP_PASSWORD`), `mail.host`, `port`, `tls`, `username`, `from` and `replyTo` set the rest
  (`MAITY_SMTP_*`). Nothing is rendered without a value.
