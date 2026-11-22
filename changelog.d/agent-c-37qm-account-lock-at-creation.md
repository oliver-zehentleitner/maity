### Changed

- hub: a human's `account_lock` row is made in the transaction that makes the account
  (registration, quickstart and the account command, the load-test seed); a migration gives
  every existing human without one its row. The lock path no longer inserts the row on first
  need, and a human found without one fails loudly (`AccountLockMissing`) instead of being
  locked on nothing. The extra transaction that made the rows before a contact or chat-access
  change (`contacts.lock_rows`, `chat_access.lock_rows`) is gone.

### Fixed

- hub: two humans naming each other at once (contacts, chat access) can no longer deadlock
  on each other's uncommitted `account_lock` insert (#1532); the race test now forces that
  interleaving with a barrier (`tests/concurrency.py`, `meet`).
