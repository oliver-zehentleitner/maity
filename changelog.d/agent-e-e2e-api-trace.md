### Changed

- web: when a step of the browser end-to-end test fails, it prints the page's last 12 API answers and writes them to `api-trace.txt` (the CI artifact): method, the route with only its known static words, status, and from a JSON body only listed fields with listed values, never the rest
