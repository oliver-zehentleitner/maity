### Added

- deploy: the Helm chart mounts a PersistentVolumeClaim as the local attachment store: `attachments.existingClaim`, `mountPath`, `quotaBytes` (into the hub and the migrate Job, with `MAITY_ATTACHMENT_DIR` and `_QUOTA`).
- deploy: the k3s setup gets the claim `maity-attachments` (`attachments.yaml`), the nightly backup tars the attachment volume next to the dump with the same
  time stamp and rotation (the `dump ok:` line carries both sizes), and `restore-attachments.yaml` puts one night's files back.
