# Credentials

How the hub stores what verifies an agent's or a runner's credential.

## A credential's verifier is sealed with the instance key when there is one, and only the migration seals older rows

**Id:** 0ce47fbe-77f9-4576-8e20-bb7f4d2a4ff2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-d9r02hn5n32y and the lead's go on its five open points, 2026-11-14
**Revisit when:** `MAITY_SECRET_KEY` becomes mandatory, the hub gets a previous-key mechanism for its sealed values, or credentials move to asymmetric keys

The verifier `sha256(<secret>)` is the HMAC key of a signed request (docs/api.md §2.2), so a
copy of the database could sign as every agent and runner. `credential.verifier` and
`runner_credential.verifier` now hold it sealed with `MAITY_SECRET_KEY` through `secretbox`,
as the hub's other stored secrets are: `s1:` and the base64 of the sealed 32 bytes, with the
table, the column and the credential's id as associated data (`auth/verifiers.py`). The CLI's
scheme is unchanged.

- **No key:** the verifier is stored as plain hex, as before, and the read path takes both
  forms; the startup check warns once with the count of plain rows.
- **Key changed or lost:** there is no previous key. A sealed row that does not open
  verifies nothing and answers as an unknown credential (401). The startup check logs how many
  there are, and those agents and runners join again. This is the path every sealed value of
  the hub already takes (a forge webhook secret that does not open counts as not set).
- **Older rows:** only the migration `20261114020000_sealed_verifiers` seals them, with the
  key that `maity-hub migrate` hands it. A start of the hub writes nothing. A key added later
  leaves the older rows plain until their credential is replaced, and the startup check counts
  them. The downgrade opens every sealed row and refuses without the key that sealed it.
- **The migration loops over rows:** sealing needs a random nonce and AES-GCM per row, which
  SQL does not have, so this migration does not follow the set-based backfill rule
  (persistence.md, 319da070). It reads the rows once and writes them in executemany batches of
  500. The number of rows is the number of credentials ever issued, not humans × rows.

**Reason:** this is the protection the cost paragraph of §2.2 promised ("an encrypted
verifier column with a key from the hub's environment"), and it reuses the one sealing helper
and key the hub already has. Startup stays read-only, which matters once several pods start
together (replicas.md).

**Rejected alternatives:**
- Making `MAITY_SECRET_KEY` mandatory: it would break every install and local run without one.
- A pepper stored in the database, as the address lock uses without a key: it sits beside the
  rows it would protect, so a database copy carries both.
- Sealing the plain rows at hub start: it writes at startup, which several pods would race on.
- A previous-key setting for rotation: no other sealed value has one, and it is a mechanism of
  its own for every sealed field; not in this card.
- Sealing only `credential` and leaving runner credentials plain: a runner's verifier is an
  HMAC key with the same exposure.
