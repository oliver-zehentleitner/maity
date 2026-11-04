### Changed

- k3s setup (`deploy/k3s-single/backup.yaml`): the nightly dump and attachment tar are encrypted with
  gpg to the public key in the Secret `maity-backup-key` and written 0600 (`maity-<ts>.dump.gpg`,
  `maity-<ts>.attachments.tar.gpg`). Without the Secret, or with a private key in it, the Job fails
  with a `backup failed:` line. `restore-attachments.yaml` now takes the tar streamed in after it is
  decrypted off the instance, and the database restore reads the decrypted dump whole before
  `pg_restore --clean` runs. Each goes through one block of commands that stops before the
  cluster when the decryption or the check of the file fails; the tar must reach its end-of-archive
  block. The Job takes the tar's SHA-256 with the stream, keeps the stream in a scratch volume and
  leaves the attachment volume as it is unless what arrived has that digest. The install guide covers generating the key, copying backups off the
  instance every night, unencrypted backups left from before, what to do when a key or backup was
  exposed, and a test restore that reads the whole file. An installation upgrading from unencrypted
  backups creates `maity-backup-key` before it applies the new `backup.yaml`.
