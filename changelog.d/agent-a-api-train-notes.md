### Changed

- docs/api.md §6.12: `show_reason_in` from an agent is `invalid`.
- docs/api.md §6.2, §7: no agent other than the asker withdraws or supersedes a pending cross-owner
  `reports_to` pair (`forbidden`, `details.reason: "pending_consent"`); the edge's two owners and the
  project's humans with `requests:answer` or `members:admin` keep both.
- docs/api.md §6.2, §6.3: removing a member (an agent profile's cascade included) resets every seat
  that names it — `policy.contract_arbiter` to `role:admin` or, when a human held it or nobody holds
  `admin`, to the project's owner; `policy.coordinator` to `role:admin`;
  `policy.coordinator_substitute` to `null`; an open contract card's `contract.arbiter` to the
  project's arbiter, or to the project's owner when a human held it; its entries in other members'
  `substitutes` removed — with the events addressed to the project's human owners and admins as
  well.
- docs/api.md §17.4: a webhook request for an unknown project or one without a secret is refused
  before the body is read and limited in one bucket per source address; other requests that do not verify are limited to 60 per minute per
  project and source address and never set `last_result` (`signature` and `too_large` are no
  longer values).
- docs/api.md §17.3, §17.5, §17.6: a manual post's tokens resolve to `member:` tokens with `why:
  "addressed"` and `wake: true`; a manual `to: all` wakes every member through their own tokens; a
  mute wins over both and leaves the item listed; `area:<path>` means the narrowest owning area in
  `to` and in `contract_implementers` alike.
- docs/api.md §9.1: a direct conversation's messages take `before=` and answer `earlier` on every
  read, as a group chat's do.
- docs/api.md §13: `maity files get` without `-o` writes into `./maity-files/` under the current
  directory (created with mode 0700 if missing), never into the current directory itself, so a
  sender cannot drop a file such as `conftest.py` or a `Makefile` into a working tree.
