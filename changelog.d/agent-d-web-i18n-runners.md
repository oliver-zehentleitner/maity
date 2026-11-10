### Changed
- web: the Runners view's texts come from the catalog (`i18n/en.json`):
  presence, hosts and pools, tools and modes, who can see what, the
  pairing steps and the actions. A host with one agent slot reads "1 of 1
  agent running"; a tool unavailable for a reason the dashboard does not
  know says "is not available (<reason>)". The starter configuration
  stays English, as the runner reads it.
