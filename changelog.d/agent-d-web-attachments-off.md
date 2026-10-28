### Fixed

- Dashboard: an instance with attachments off (409 `attachments_not_configured`) is treated like a hub without attachments: Attach files and Delete are not offered, and the e2e run no longer reports it. An upload or a delete that meets it says so in place, and Project settings says it beside the storage line. Fixture mode has `?attachments=off`.
- e2e: the hub runs without an attachment store until messages name their attachments; the attachments step checks attachments off (no Attach files, no Delete), and each 409 for the pending uploads is judged by its own answer: only GET, that path and the code `attachments_not_configured` pass. `make check` runs a test of that judgement (`tools/test_e2e_harness.py`).
