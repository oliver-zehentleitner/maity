### Changed

- web: when a step of the browser end-to-end test fails, it prints the page's last 12 API answers and writes them to `api-trace.txt` (the CI artifact): method, path without query and token segments, status and a few allowlisted body keys, never the rest
