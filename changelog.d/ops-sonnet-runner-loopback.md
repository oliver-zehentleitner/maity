### Changed

- deploy: on a rented runner server the firewall chain of the runner user lets loopback through (the test suite starts servers of its own on any port) and keeps
  ssh, the metadata service and the private networks closed; the bootstrap's self-test probes an arbitrary loopback port.
