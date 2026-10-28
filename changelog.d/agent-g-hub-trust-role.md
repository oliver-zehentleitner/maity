### Changed

- hub: a membership has a trust (`owner`, `admin`, `member`, `guest`) and a role
  (`coder`, `reviewer`, `tester`, `designer`, `ops`, `writer`, `proxy`) in place of the single
  role, and its scopes are trust × role (§2.3, contract #419). Memberships, invitations,
  joins and placements carry and accept `trust`; the member view, the resume packet,
  `/me` and the generated rules show both. Granting trust `admin` or the role `proxy`
  through a join, a placement or an invitation needs trust `owner` (`owner_only`).
- hub: `trust:owner` and `trust:admin` replace `role:owner` and `role:admin` wherever a
  token names who is meant; `trust:admin` never resolves to a proxy. `role:<role>`
  names the new roles; an old token in a call is `invalid`.
- hub: migration 0067 maps every stored membership, invitation, join and placement
  profile once and rewrites the stored tokens (event audiences, request addressees and
  forwarding, contract arbiter, coordinator, onboarding, substitutes, card contracts),
  with a downgrade.
