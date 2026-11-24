### Fixed

- hub: a request held for an agent of another owner stays out of that agent's request list
  under `to=all` and out of its open-request counts, also when it may answer requests, as the
  request itself and `to=me` already were.
- hub: a proxy finds the open requests addressed to the owner under `to=me`, in the list and
  in its counts, so it can relay them as docs/api.md §7 says.
