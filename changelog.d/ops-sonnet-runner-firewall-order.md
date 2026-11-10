### Changed

- deploy: on a server prepared by `bootstrap-server.sh` the runner units require and follow the firewall unit, which starts before
  the runner user's manager; the Docker key file must hold exactly one key; the self-test also probes `[::1]:22`.
