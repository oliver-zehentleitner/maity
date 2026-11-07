### Fixed

- Hub tests: `test_public_why` no longer fails at random. Its apps start no public-pages worker, whose start-up render, late on a loaded runner, wrote the Why page back with the settings the app was started with after a test had changed them.
