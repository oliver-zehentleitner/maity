### Security

- hub: with `MAITY_SECRET_KEY` set, the verifiers of agent and runner credentials are stored
  sealed with the instance key, as the hub's other stored secrets are, so a copy of the
  database alone signs as no agent or runner. Without the key they are stored as before. The
  CLI is unchanged. A key that is changed or lost opens no sealed verifier: those agents and
  runners join again. The hub logs at startup how many live verifiers its key does not open
  and how many are still stored unsealed.
- Operators: `maity-hub migrate` seals the verifiers already stored only when it runs with
  `MAITY_SECRET_KEY` set (on Helm, `secretKey.existingSecret` reaches the migrate Job). A key
  added later leaves the older verifiers unsealed until their agent or runner joins again. A
  downgrade past this migration needs the same key.
