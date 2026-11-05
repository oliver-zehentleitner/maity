### Added

- hub: the instance-wide attachment storage limit of §16.5. `max_attachment_storage` (`MAITY_MAX_ATTACHMENT_STORAGE`, default `unlimited`) can be set in the admin section Limits, and `attachment_storage_used` shows the total. An upload over the limit is refused with `attachment_quota`, `details.scope: "instance"`.
- web: the Limits section shows and takes the storage in GiB, with what is stored now; an upload refused for the hub's storage says so.
