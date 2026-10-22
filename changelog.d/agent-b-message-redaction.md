### Changed

- hub: `…/conversations/{agent_id}/messages` items carry `redacted` (as the list preview
  does) and `redaction: {at, by, reason}` for a redacted message, `null` otherwise; the
  reason only for the human owners and admins and the redactor (`docs/api.md` §8.5, §9.2)
