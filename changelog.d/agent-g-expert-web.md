### Added

- web: the role `expert` in every role list, with its label and help (not in a card's needs: an expert takes no cards).
  The Team list shows "Expert for …" under an expert's role, and the member's page shows that and its sources. The
  agent's owner, or an admin, sets the two fields (§6.2 "An expert's fields") in their own form, on Team and on the
  agent's card in Agents, sent alone in one `PATCH`.
- docs: `humans.md` (Team, Trust and role) and `agents.md` (asking `role:expert`; working as an expert) say what an expert is
  and where its fields are set.
