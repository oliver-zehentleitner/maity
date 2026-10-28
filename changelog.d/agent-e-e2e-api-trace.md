### Changed

- web: when a step of the browser end-to-end test fails, it prints the page's last 12 API answers with the start of their bodies and writes them to `api-trace.txt` (the CI artifact), so that a hub answer can be told from a stale drawing
