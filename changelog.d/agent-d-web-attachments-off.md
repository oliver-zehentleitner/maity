### Fixed

- Dashboard: an instance with attachments off (409 `attachments_not_configured`) is treated like a hub without attachments: Attach files and Delete are not offered, and the e2e run no longer reports it. An upload or a delete that meets it says so in place, and Project settings says it beside the storage line. Fixture mode has `?attachments=off`.
