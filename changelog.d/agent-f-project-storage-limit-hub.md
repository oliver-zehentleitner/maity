### Added

- Hub and dashboard: the admin limit `max_attachment_storage_per_project` under Limits
  (docs/api.md §16.5), with the environment variable `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`;
  1 GiB by default, 1 MiB to 1 PiB or `unlimited`. An upload over it is `attachment_quota` with
  scope `project`; under `unlimited` the project view's `attachments.quota` is `null`, and the
  project settings say "no limit".

### Removed

- Hub: `MAITY_ATTACHMENT_QUOTA` is no longer read; set `MAITY_MAX_ATTACHMENT_STORAGE_PER_PROJECT`
  or the admin field instead.
- Helm chart: `attachments.quotaBytes`; a values file that still sets it is refused by the schema.
