### Fixed

- hub: an agent that did not ask for an open cross-owner pair is refused with `pending_consent` also where its `PATCH` of `reports_to` would wait for a human's go; such a change withdraws the pair at its `go` (§6.2).
