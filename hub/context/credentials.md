# Credentials

How the hub stores what verifies an agent's or a runner's credential.

## Sealing a credential's verifier is opt-in behind MAITY_SEAL_VERIFIERS, default off; seal-verifiers seals older rows

**Id:** 0ce47fbe-77f9-4576-8e20-bb7f4d2a4ff2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-d9r02hn5n32y and the lead's go on its five open points, 2026-11-14; the switch: card tsk-47b7fwkvft30 by lead lotse, 2026-11-15, and lotse's decision to edit the migration in place (seq 136270, 136323)
**Revisit when:** sealing is switched on for good (tsk-ebc2fhdxttm7 adds a sealed-only setting), `MAITY_SECRET_KEY` becomes mandatory, the hub gets a previous-key mechanism for its sealed values, or credentials move to asymmetric keys

The verifier `sha256(<secret>)` is the HMAC key of a signed request (docs/api.md §2.2), so a
copy of the database could sign as every agent and runner. `credential.verifier` and
`runner_credential.verifier` can hold it sealed with `MAITY_SECRET_KEY` through `secretbox`,
as the hub's other stored secrets are: `s1:` and the base64 of the sealed 32 bytes, with the
table, the column and the credential's id as associated data (`auth/verifiers.py`). The CLI's
scheme is unchanged.

- **The switch:** the hub seals what it writes only with `MAITY_SEAL_VERIFIERS=1`, which needs
  the key (the hub does not start without it). Default off: new verifiers are stored as plain
  hex, as before. The owner decided that sealing is built now and switched on later, in a
  separate step; the setting is that step. The read path takes both forms whatever the
  setting, so switching it off again after a test locks no one out while the key is set.
- **No key:** the verifier is stored as plain hex, and a sealed row verifies nothing. The
  startup check logs the count of plain rows once and says whether sealing is on (a warning
  with sealing on, info with it off).
- **Key changed or lost:** there is no previous key. A sealed row that does not open
  verifies nothing and answers as an unknown credential (401). The startup check logs how many
  there are, and those agents and runners join again. This is the path every sealed value of
  the hub already takes (a forge webhook secret that does not open counts as not set).
- **Older rows:** `maity-hub seal-verifiers` seals them, and refuses unless the setting is on
  and the key set. It seals only plain rows (a row is written only while it still holds the
  plain value read), so a second run seals nothing; it prints the count per table and in all.
  A start of the hub writes nothing.
- **The migration only widens:** `20261114020000_sealed_verifiers` was edited in place,
  revision ID and down_revision kept; in 0.1.0a6 it also sealed every row when given the key.
  Our instances go from 0.1.0a5 to 0.1.0a7 (the deploy of 0.1.0a6 was cancelled), so they run
  only the form that widens; a later migration could not take back rows already sealed. A
  database that ran the 0.1.0a6 form has the revision recorded and does not run it again, and
  its sealed rows keep working because the read path takes both forms. The downgrade opens
  every sealed row and refuses without the key that sealed it.
- **Sealing loops over rows:** sealing needs a random nonce and AES-GCM per row, which SQL
  does not have, so `seal-verifiers` and the migration's downgrade do not follow the set-based
  backfill rule (persistence.md, 319da070). They read the rows once and write them in
  executemany batches of 500. The number of rows is the number of credentials ever issued, not
  humans × rows.

**Reason:** this is the protection the cost paragraph of §2.2 promised ("an encrypted
verifier column with a key from the hub's environment"), and it reuses the one sealing helper
and key the hub already has. Startup stays read-only, which matters once several pods start
together (replicas.md).

The switch exists because the owner decided to build sealing but turn it on later, in a
separate step (tsk-47b7fwkvft30). A command rather than `migrate` with the setting on seals the
older rows: it is explicit, runs again safely, and tsk-ebc2fhdxttm7 asked for the same command.

**Rejected alternatives:**
- Sealing older rows in `migrate` when the setting is on: it mixes a data step into the schema
  step, and the setting would have to reach the migration.
- Leaving the 0.1.0a6 migration as it was and adding one on top: the instances still on
  0.1.0a5 would run the sealing form on their way to 0.1.0a7, and no later migration could
  undo it.
- Making `MAITY_SECRET_KEY` mandatory: it would break every install and local run without one.
- A pepper stored in the database, as the address lock uses without a key: it sits beside the
  rows it would protect, so a database copy carries both.
- Sealing the plain rows at hub start: it writes at startup, which several pods would race on.
- A previous-key setting for rotation: no other sealed value has one, and it is a mechanism of
  its own for every sealed field; not in this card.
- A sealing key derived per purpose (`secretbox.derive`, as the HMAC keys and peppers use):
  no other sealed field has one; every AES-GCM seal uses the instance key, and the associated
  data (table, column, id) already separates the fields.
- Sealing only `credential` and leaving runner credentials plain: a runner's verifier is an
  HMAC key with the same exposure.
