### Fixed

- deploy: the chart's default ingress-nginx annotations set `proxy-body-size`
  to `11m`, so attachment uploads up to the hub's 10 MiB pass the ingress;
  `deploy/helm/check.sh` checks that the value stays above the hub's cap.

### Added

- deploy: `deploy/k3s-single/uploads.yaml`, a Traefik route for the
  attachment upload alone that buffers its body (at most 11 MiB) before the
  hub reads it.
