### Added

- deploy: the Helm chart mounts a PersistentVolumeClaim as the local attachment store: `attachments.existingClaim`, `mountPath`, `quotaBytes` (into the hub and the migrate Job, with `MAITY_ATTACHMENT_DIR` and `_QUOTA`).
- deploy: the k3s setup gets the claim `maity-attachments` (`attachments.yaml`), the nightly backup tars the attachment volume next to the dump with the same
  time stamp and rotation (the `dump ok:` line carries both sizes), and `restore-attachments.yaml` puts one night's files back.
- deploy: `helm-upgrade.sh` demands the attachment tar in the dump's mark when `DUMP_REQUIRES_ATTACHMENTS=1` (set it for a release with `attachments.existingClaim`; the old
  backup script has no tar), and the backup Job refuses to write a tar that would not fit twice on the node's disk (the claim's size is not enforced on local-path).

