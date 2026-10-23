### Fixed

- hub: a request with a body to an API path no route serves answers `404 not_found` before
  the 64 KiB cap and without reading the body, instead of `413 payload_too_large`; a path a
  route serves with another method, or that differs by a trailing slash, stays routed
  (the cap, then `405` or the `307` redirect)
