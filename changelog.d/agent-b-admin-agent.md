### Added

- hub: an agent with the `admin` role manages the member and reviewer agents below it
  (`docs/api.md` §2.3 ᵃ, #139) — `PATCH …/members/{id}` with `reports_to`, `areas`,
  `briefing`, `paused` and `role` between `member` and `reviewer`, never on itself or on
  `admin`/`proxy` agents; a removal, and a role change or pause of a reviewer or the
  contract arbiter, is a `member_change` proposal (`202`, a consent request to the owner
  that only a human answers) applied on `go` with the agent as actor; role changes and
  removals emit `member_changed_by_agent` to `role:owner`; its pause names it as `by`, is
  not cleared by the paused agent's resume, and it never lifts or replaces a human's;
  `members:admin` is listed in its scopes, with the two operations
- hub: `humans_only` (`403`, `details.reason`) for every agent, whatever its role, on a
  human's membership, `capabilities`, the `proxy`/`admin`/`owner` roles, the policy fields
  humans decide (`spawn_consent_by`, `signing`, `tag_authority`, `on_runner_revoke`,
  `spawn_requests`), `rules_markdown` and archiving a project

