### Fixed

- hub: the forge's per-token budgets drop the ones that say nothing any
  more once more than 256 are known, and the repository visibility and
  publicness kept per token drop expired entries and keep at most 4096;
  hourly installation tokens no longer pile up in memory.
- hub: a contract text read the forge does not answer no longer leaves
  its lock behind.
- hub: the count of dropped registration requests forgets the hour
  before on every addition, not only when an admin reads it.
