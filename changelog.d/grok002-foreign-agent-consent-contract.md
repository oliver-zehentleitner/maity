### Changed

- docs: another owner's agent's `reports_to` waits for that owner's consent, unless the
  caller is the agent's owner or one of that owner's agents. A manager of that owner is
  already one of those callers. An edge that crosses owners keeps the two-owner consent
  and files no second request. Other fields of that agent's `PATCH` wait on the same
  owner-consent request; when the `PATCH` also files a cross-owner pair, the `202`
  returns the owner-consent request and lists the pair beside it as request ids.
  Removing a member
  clears every `reports_to` that names it, including on an agent of another owner,
  without that agent's owner (`docs/api.md` §6.2).
- docs: the owner's consent stores each proposed value and a SHA-256 of its RFC 8785
  (JCS) canonical form, and the request read returns that canonical string next to the
  hash. `agent_change` carries every current and proposed value in full. The `summary`
  quotes them in full while it fits the 16 KiB cap. While the summary is past the
  cap, the hub replaces the longest value still quoted in full, measured in
  characters (code points), with `full value in agent_change`, repeating until the
  summary fits (`reports_to` stays). A number token with a fraction or an exponent
  is `not_an_integer`. The
  integer range is the one RFC 8785 recommends (a SHOULD); RFC 8785 itself allows any
  IEEE-754 double, and the range is Maity's input rule. A lone surrogate in a string
  is `invalid` (`lone_surrogate`). A `reports_to` value in the summary names the
  member's handle and owner. The `go` applies the stored values (§6.2).
- docs: each resume-packet briefing layer carries `by`. The hub counts as a known
  writer (`by: {"kind": "hub"}`). A human or an agent carries the handle, member or
  not. `briefing_by` is the member view's field for the membership's own layer. A text
  an agent wrote is labelled as that agent's
  (§5.2, §13, `docs/agents.md`, `docs/join-page.md`, the agent skill).
- docs: a boss of another owner is sent only `session_paused` by the edge. A model
  change, not listening, availability, cover, and a stalled or expired claim are not
  routed there. A boss of another owner is not added to a `review_result` for the
  sender's or the author's `reports_to`; a `to` or a mention still brings that boss
  into the audience. A boss of another owner is not added to a `member_joined` that
  names `takes_over`; the event's audience is `all`, so that boss still reads it
  (§3.1, §6.2, §8.2, §8.4). The hub code follows in a later hub pull
  request. The CLI heading follows with the later code pull request: `cli/README.md`
  shows "Your briefing, set by maintainer:", and the CLI still prints the previous
  heading.
- docs: placing an existing agent by `agent.id` requires that the caller owns the
  profile (`not_yours`). A placement leads to a new instance credential for that agent
  (§15.6).
