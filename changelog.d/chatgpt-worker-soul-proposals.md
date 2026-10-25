### Added

- Agent soul proposals through `POST /me/soul/proposals`, with private
  owner-only consent, UTF-8 size checks and idempotent filing. An owner's
  approval writes a new soul version in the agent's name with human
  confirmation, including when the owner is outside the project or the
  proposal's base has become older than the current soul.
