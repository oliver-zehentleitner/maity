### Changed

- docs/api.md: notifications are only what a human has to react to (§18.1). The kinds are now
  `inbox`, `chat`, `mention` and `security`; `card`, `ticker`, `jour_fixe`, `keep_the_why`,
  `agent`, `system` and `registration` are no longer notifications, and the events behind them
  are unchanged. An agent's outage (§15.7) and an unconfirmed Keep the Why commitment (§6.23)
  become personal requests of class `info` to the agent's owner, filed once and withdrawn by the
  hub when what they report ends; such requests carry `filed_by: "hub"` and reach the owner
  only (§7); a pending registration (§16.4) and a disabled mail address
  (§18.7) are `inbox` items counted and listed until decided or fixed, never mailed; `registration_approved` notifies
  nobody; a jour fixe reaches humans through its requests and the round itself (§20.9). The
  derive reads only chat and mention messages, request events and account records. `counts`,
  `by_project`, the `kind` filter and the settings carry the four kinds only; old stored kinds
  are dropped on read and on the next `PATCH`, and a removed kind in a request is `invalid`
  (`removed_kind`). Items lose `reason`; a card watch (§6.4) no longer notifies.
