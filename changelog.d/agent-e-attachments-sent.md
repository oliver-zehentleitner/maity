### Added

- hub: attachments (§8.7), the rest: `DELETE /projects/{slug}/attachments/{id}` also deletes an attachment
  a message carries (its uploader, a human in the chat, or a human with `members:admin` for a project
  message), leaves a tombstone and emits `attachment_deleted`; an owner outside the project reads a
  group chat's attachments as it reads the chat; a background sweep removes pending uploads after 24
  hours and bytes no row names; removing a member deletes its pending uploads.
