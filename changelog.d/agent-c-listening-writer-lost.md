### Fixed

- hub: the listening registry on PostgreSQL no longer leaves itself started without a writer. A first heartbeat that fails undoes the start, and a stop puts its end marker in the queue only for a writer that reads it. Before, the marker ended the next app's writer at once, and the next `listening.reset()` (tests) waited for ever. That wait, and `listening.written()` from #1251, now ends with an error after 30 s.
