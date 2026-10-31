### Added

- cli: `maity report` prints the branch, head and pull request it reports before sending, and
  refuses (exit 4) a pull request that is not the card's: one the card's pull request links do
  not include, or another one than its last report's while that one is still open. A checkout
  without a found pull request (none, or unknown without gh) is refused on such a card too. The
  message says to report from that pull request's branch.

### Changed

- cli: the handover's pointer to page on says that the read returns every event the member may
  read from there, and without a usable `after` it starts at the packet's `events.after` instead
  of the last event shown.
