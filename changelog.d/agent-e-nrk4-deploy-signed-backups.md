### Added

- deploy: the k3s backup Job (`deploy/k3s-single/backup.yaml`) signs each encrypted backup with the key in the Secret
  `maity-backup-signing-key` and writes `<file>.sig` next to it; the signature carries the file's name with its time
  stamp. The documented restore blocks (docs/install/README.md, `restore-attachments.yaml`) check the signature before
  they decrypt against the fingerprint in `MAITY_BACKUP_SIGNER`, and stop when that is not set, or the signature is
  missing, does not verify, is by another key, by a revoked or expired key, was made for another file name, or holds
  more than one signature. `MAITY_RESTORE_UNSIGNED=1` is the emergency switch: the block restores without the check and
  says so. The guide's key setup, step by step for the operator who keeps the key, replaces the signing key when run
  again.
  `deploy/scripts/test-backup-signing.sh` runs the Job's scripts with a real gpg.

### Changed

- deploy: without the Secret `maity-backup-signing-key` the backup Job writes unsigned backups and warns as the first
  line of its log; a key there that cannot sign, can also decrypt, or is the key in `maity-backup-key`, and a Secret
  with more than one key, fail the Job. Upgrade note: make the signing key on the restore machine and create the
  Secret as in docs/install/README.md, step 4 of the k3s walkthrough
  (`gpg --batch --passphrase "" --quick-gen-key "maity backup signing <you@example.org>" ed25519 sign never`, export
  its private key into `maity-backup-signing-key` as `backup-signing.key`), apply the new `backup.yaml`, and set
  `MAITY_BACKUP_SIGNER` to its fingerprint where you restore. Until then the backups stay unsigned. Restoring a backup
  without a valid signature, which includes every backup from before the signing key, now needs
  `MAITY_RESTORE_UNSIGNED=1` in the restore shell.
