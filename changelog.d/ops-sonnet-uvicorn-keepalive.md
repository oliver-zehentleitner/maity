### Fixed

- hub: `maity-hub serve` keeps idle connections open for 120 s instead of uvicorn's 5 s,
  so a proxy that pools idle backend connections no longer sends a request into one the
  hub just closed (a sporadic 502).
