### Fixed

- Dashboard: an instance with attachments off (409 `attachments_not_configured`) is treated like a hub without attachments: Attach files and Delete are not offered, and the e2e run no longer reports it. An upload or a delete that meets it says so in place, and Project settings says it beside the storage line. Fixture mode has `?attachments=off`.
- e2e: the hub runs with an attachment store (`MAITY_ATTACHMENT_DIR`), so the attachment step uploads for real. A hub with attachments off is a case of its own in that step: no Attach files, no Delete, and only its 409 `attachments_not_configured` answers, checked by their code, are not reported.
