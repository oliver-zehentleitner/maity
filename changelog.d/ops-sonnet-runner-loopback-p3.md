### Changed

- deploy: the bootstrap's self-test also probes the machine's own IPv6 address and a listener on `::1`, and prints a note for anything else that listens on loopback or on all addresses and is open to the runner user.
