# Credentials

How the hub stores what verifies an agent's or a runner's credential.

## Sealing a credential's verifier is opt-in behind MAITY_SEAL_VERIFIERS, default off; seal-verifiers seals older rows

**Id:** 0ce47fbe-77f9-4576-8e20-bb7f4d2a4ff2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the card tsk-d9r02hn5n32y and the lead's go on its five open points, 2026-11-14; the switch: card tsk-47b7fwkvft30 by the lead, 2026-11-15, and the lead's decision to edit the migration in place (seq 136270, 136323); sealed-only, the counts and reseal on use: card tsk-ebc2fhdxttm7, its plan and the lead's approval, 2026-11-17 (seq 152498, 152518, 152522, 153623)
**Revisit when:** sealing is switched on for good (both settings on in production, or made the default), `MAITY_SECRET_KEY` becomes mandatory, the hub gets a previous-key mechanism for its sealed values, or credentials move to asymmetric keys

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
  plain value read), so a second run seals nothing. It prints `sealed N, already sealed M,
  plain left K` per table and in all, revoked rows counted, and exits 1 while K is not 0 after
  a run (a plain row written meanwhile, by an old pod of a rolling deploy). `--dry-run` only
  counts and needs neither the setting nor the key, so an operator can see the numbers before
  switching anything on. A start of the hub writes nothing.
- **Reseal on use:** with sealing on, a plain row that has just verified a call is sealed in
  the update of `last_used_at` that every authenticated call already makes (agent and runner),
  guarded as the command is (a `CASE` on the plain value read). It costs no statement of its
  own and shrinks the window, but an idle credential is never resealed, nor is an isolated
  agent's (its calls write nothing), so it replaces neither the command nor the gate.
- **Sealed only:** `MAITY_SEALED_VERIFIERS_ONLY=1` (default off) makes a plain row verify
  nothing. It needs `MAITY_SEAL_VERIFIERS=1` (a configuration error otherwise), since without
  sealing every new join would write a plain row that is refused at once. The hub does not
  start while a live plain row is left: the error names the count and `seal-verifiers`, so in a
  rolling update the rollout stalls with the old pods still serving instead of locking agents
  out; with `Recreate` (the chart's single-pod default) or a single process the hub stays down
  until `seal-verifiers` has run or the setting is unset again. Revoked rows do
  not count there; they are refused anyway, and the command still seals them.
- **The refusal says nothing new:** a refused plain row takes the path of a sealed row the key
  does not open: 401 `unauthenticated` on a bearer call (what an unknown id gets) and 401
  `signature_invalid` on a signed one. That the signed path differs from an unknown id is
  older than this setting and shows nothing about sealing. The leak check still reads plain
  rows, so a leaked plain credential is revoked even while it is refused; switching the setting
  off again would otherwise bring it back.
- **Production:** both switches are off by default everywhere, the Helm chart included; an
  upgrade turns nothing on. Switching them on is the owner's decision after a deploy, in the
  order docs/install/README.md ("Backups") gives.
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
- Refusing plain rows only at runtime, with no startup gate: a setting switched on too early
  would lock out every agent and runner still on a plain row, on every pod at once.
- A refusal of its own for a plain row (a new error code or detail): it would tell a caller
  that the instance seals, and which credentials are not sealed yet.
- Making the signed path answer `unauthenticated` for a refused or unopenable row, as an
  unknown id does: it changes an answer that exists already, for no gain against the
  verifier's exposure.
- Reseal on use as a statement of its own: it would add a write to the sealed path's every
  call; the `last_used_at` update already touches the row.
- Counting revoked rows in the startup gate: they verify nothing either way, and an old
  revoked row would block the start for no protection.
