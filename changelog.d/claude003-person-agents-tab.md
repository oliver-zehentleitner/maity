### Added

- web: `/<handle>/agents` signed in is the tab **Agents** of the person's view, beside
  **Profile** at `/<handle>`: the agents `GET /people/{handle}` lists, drawn as the public
  agents page draws them (§6.27, §16.9, §16.11). Without a session the dashboard's
  read-only copy of that page (`person_agents`) carries the same two tabs.
