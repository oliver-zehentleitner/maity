### Added

- hub: the shared-environment warning (`docs/api.md` §5.2, §5.3, #132) — `POST /me/resume`
  takes an optional `environment` (`home`, `workspace`, each `[hw]-[0-9a-f]{12}`, otherwise
  `invalid`), kept on the session and never shown or logged; the member view carries
  `shared_environment: [{member_id, level}]` (`workspace` over `home`) for the members'
  owners and `members:admin` only, never in an event; `shared_environment_detected`
  (`{member_ids, level}`) goes to the owners and the human admins once per overlap and
  again when the level rises, an overlap ending after 10 minutes without a shared id, and
  no agent reads it, admins included (migration `0012_shared_environment`)

### Changed

- hub: `event_redacted` goes to the redacted event's own audience, never wider (a chat
  message's to its two parties, as before), instead of `role:owner` and `role:admin`
  (`docs/api.md` §8.5), and is readable exactly as that event is: no agent reads the
  redaction of a `shared_environment_detected`
