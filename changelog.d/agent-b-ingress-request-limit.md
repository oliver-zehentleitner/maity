### Added

- deploy: an optional per-client request limit at the ingress, off by
  default: `ingress.requestLimit` in the chart (rate, burst and open
  requests per client address, as ingress-nginx annotations) and
  `deploy/k3s-single/request-limit.yaml` for Traefik, with smaller caps for
  attachment uploads. Switch it on once every agent runs a `maity` whose
  `maity wait` retries a 429.
