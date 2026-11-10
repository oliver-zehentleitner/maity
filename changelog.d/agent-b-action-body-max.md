### Changed

- hub, cli: the body of a proxy's `action` is capped at 48 KiB instead of 64 KiB, so that a larger one is refused as `too_large` and not as a request over the cap (§2.3, §7). The CLI also refuses a body that only its JSON escaping would take over the cap, by name.
