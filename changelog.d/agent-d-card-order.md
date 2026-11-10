### Added

- web: **Board** columns stand in the hub's card order (rank, then age); an owner or admin places
  an open card with **Place** (Move up/down, To the top/bottom) or by dragging it over another card
  of its column (`POST …/move`, docs/api.md §6.4); the order changes once the hub answered, a
  neighbour that moved meanwhile re-reads the board
