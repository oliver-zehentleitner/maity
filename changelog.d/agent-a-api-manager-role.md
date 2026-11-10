### Added
- docs: the role `manager` and its scope `line:lead` (§2.3): a member that
  leads its line of the org chart (everyone whose `reports_to` chain
  reaches it), with rights over that line only; managers nest, and a
  `reports_to` chain is capped at 8 members.
