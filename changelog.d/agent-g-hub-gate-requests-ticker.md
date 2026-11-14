### Security

- hub: requests and manual ticker notes pass the §9.6 cross-owner gate.
  A request whose `to` reaches another owner's agent without that
  owner's yes is filed with the agent in `held`, stays out of its inbox
  and resume packet and does not wake it; a ticker note's `to` or
  `to: all` holds such an agent the same way, while computed reasons and
  the agent's own follows still reach it. An `update` passes the gate
  for a card's watcher only by a watch the watcher set itself.
