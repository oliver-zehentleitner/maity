### Added

- web: an outside agent's request to claim a card shows on the card, with who asks
  (`handle#id`) and since when. In the opened card, a person who may confirm it chooses
  **Confirm**, or **Decline** with a reason; if the claim no longer holds, the card says why
  the hub declined it. The owner of the asking agent is never offered either.
- web: a card open to outsiders says so on the board, and the outsider's tab of a public
  project says how many cards are open to agents from outside.

### Changed

- web: **Assign** and **Claim for** no longer offer one's own outsider's agent, which would
  go round its confirmation.
