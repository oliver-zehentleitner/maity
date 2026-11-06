### Fixed

- Web, Sign in another device: approving the new device asks for the second factor in the dialog when the
  hub wants a fresh one (§2.8.4), then sends the approval again. Before, an enrolled human whose second
  factor was older than 10 minutes only saw "Not sent" with the hub's refusal. Cancel leaves the approval
  open.
