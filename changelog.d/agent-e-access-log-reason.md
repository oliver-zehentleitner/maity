### Added

- Hub request log: a 403, and any other 4xx whose details carry a `reason` or a `scope`, ends its
  line in `error=<code>` with `reason=` and `scope=` where present, so ops can tell which check
  refused a call (docs/api.md §1.1). Only code tokens are written, anything else as `?`; nothing
  else of the answer or the request reaches the line.
