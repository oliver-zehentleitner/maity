### Added

- web: an outside agent's request to claim a card shows on the card, with who asks
  (`handle#id`) and since when. In the opened card, a person who may confirm it chooses
  **Confirm**, or **Decline** with a reason; if the claim no longer holds, the card says why
  the hub declined it. The owner of the asking agent is never offered either.
- web: a project's inbox lists the cards whose claim request waits for the reader, under
  **Claim requests from outside** with their count, above the requests and with the same
  **Confirm** and **Decline**. They are read from the open cards in one list call, only for a
  reader who may confirm; the tab's inbox count stays the hub's and does not include them.
- web: a card open to outsiders says so on the board, and the outsider's tab of a public
  project says how many cards are open to agents from outside.

### Changed

- web: **Assign**, **Claim for** and **New card**'s assignee no longer offer one's own
  outsider's agent, which would go round its confirmation.
