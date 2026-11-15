### Changed

- hub: 0.1.0a7 starts the two features 0.1.0a6 switched on by default switched off, so an
  upgrade from 0.1.0a5 changes neither how credentials are stored nor who reaches a group chat.
  Sealing the verifiers of agent and runner credentials at rest is on with
  `MAITY_SEAL_VERIFIERS=1` and `MAITY_SECRET_KEY` set (Helm: `secretKey.sealVerifiers: true`
  with `secretKey.existingSecret`); `maity-hub seal-verifiers` then seals the verifiers stored
  before. The agent firewall's gate (§9.6) is on with `MAITY_AGENT_FIREWALL=on` on every hub
  process; its next start judges every open group chat once.
