### Added

- hub, web: site values (`/admin/settings/site-values`, §16.7.3): `{{name}}` in a site file is replaced with the value kept under **Import or export everything** when the file is imported. **Check the file** says for each placeholder whether it was replaced; one without a value blocks the save.

### Changed

- hub: a landing page, a legal page or a registration setting still holding a placeholder such as `{{name}}` is refused with `unresolved_placeholder`.
- web: `web/tools/maity-site.json` writes its placeholders as `{{name}}` instead of `[Name]`.
