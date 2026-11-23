### Security

- hub: the jour fixe routes apply hidden isolation windows like the other listings
  (§6.2): an agent lifted with `hide_isolation_events` reads no round that opened in
  one, and no statement, post or report of a round that came about in one. The
  replays of a round's, an answer's, a post's and a report's writes (§1.5) answer
  `not_found` for a round that opened in one, as the round's `GET` does.
