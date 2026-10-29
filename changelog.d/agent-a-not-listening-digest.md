### Changed

- docs: an agent instance that is not listening no longer files one request per episode; its owner gets one hourly
  digest of every instance away for the project's `policy.not_listening_minutes` (default 60), as an inbox request,
  a bell item or nothing, by the human's `not_listening` setting (§5.3, §6.1, §7, §18.1, §18.4)
