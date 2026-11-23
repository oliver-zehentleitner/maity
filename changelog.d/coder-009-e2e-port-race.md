### Fixed

- web e2e: a round that starts a mail catcher beside its own hub (the second hub, the mail
  factor, the password reset) starts the catcher first and picks the hub's port around it,
  so the catcher can no longer take the hub's port and answer its health check;
  `tools/test_e2e_harness.py` forces the old collision and holds every round to the order.
