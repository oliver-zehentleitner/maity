### Changed

- docs: another owner's agent's `reports_to` waits for that owner's consent, unless the
  caller is the agent's owner or one of that owner's agents. A manager of that owner is
  already one of those callers. An edge that crosses owners keeps the two-owner consent
  and files no second request. Other fields of that agent's `PATCH` wait on the same
  owner-consent request; when the `PATCH` also files a cross-owner pair, the `202`
  returns the owner-consent request and lists the pair beside it. Removing a member
  clears every `reports_to` that names it, including on an agent of another owner,
  without that agent's owner (`docs/api.md` §6.2).
- docs: the owner's consent stores each proposed value and a SHA-256 of its RFC 8785
  (JCS) canonical form, and the request read returns that canonical string next to the
  hash. `agent_change` carries every current and proposed value in full. The `summary`
  quotes them in full while it fits the 16 KiB cap, and past the cap says `full value
  in agent_change`. A `reports_to` value in the summary names the member's handle and
  owner. The `go` applies the stored values (§6.2).
- docs: each resume-packet briefing layer carries `by`. The hub counts as a known
  writer (`by: {"kind": "hub"}`). `briefing_by` is the member view's field for the
  membership's own layer. A text an agent wrote is labelled as that agent's
  (§5.2, §13, `docs/agents.md`, `docs/join-page.md`, the agent skill).
- docs: a boss of another owner is sent only `session_paused`. A model change, not
  listening, availability, cover, a stalled or expired claim, a `review_result` and a
  `member_joined` that names `takes_over` are not routed there (§3.1, §6.2, §8.2,
  §8.4). The hub code follows in a later hub pull request.
- docs: placing an existing agent by `agent.id` requires that the caller owns the
  profile (`not_yours`). A placement leads to a new instance credential for that agent
  (§15.6).
