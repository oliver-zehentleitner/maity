### Security

- hub: addressed work messages pass the §9.6 cross-owner gate. An `update`
  or a `review_result` from another side reaches an agent by `to`, `all`,
  a role or trust token or a mention only on its owner's yes, as a
  `notice` does, and names the agents held for it in `held`; an update's
  watchers and a review result's author and two leads (§8.4) stay open.
  Every message type that takes a `to` is now in the gate.
