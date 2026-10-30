### Fixed

- Web e2e, `join_expiry_step`: deterministic. The step moved only the browser's clock, and the next
  answer's `Maity-Server-Time` pulled the page back to the hub's real time, so the join read as open
  again now and then. The second tab now sees the hub's clock moved by the same 16 minutes.
- Dashboard, fixture hub: a review result's `review` is checked as the hub's `reviews.py` does
  (`required` for a missing field, unknown keys refused, every line break in a quote).

