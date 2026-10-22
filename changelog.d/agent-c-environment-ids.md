### Added

- cli: `maity resume` declares the session's environment (§5.2, §5.3) — `home` and
  `workspace` ids, `h-`/`w-` plus 12 hex characters of HMAC-SHA256(secret, the hub's base
  URL), from random 0600 secrets in `~/.local/state/maity/env-secret` and
  `<state dir>/env-secret`; never a path, never printed. An unreadable or loose secret
  leaves the ids out with a note; a hub that refuses the field is resumed without it.
