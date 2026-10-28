### Added

- hub: the Keep the Why commitment under `policy.keep_the_why: required` — the deadline fixed by an instance's first resume, `commitment`, `acknowledged_at`, `acknowledge_by` and `ack` in the resume packet, `POST /me/keep-the-why/ack` (`keep_the_why_acknowledged`), `keep_the_why_acknowledged_at`/`_by` on instances and `keep_the_why_unconfirmed` on the member view; migration 0070 (§6.23)
- hub: the commitment's reminder (`keep_the_why_reminder`, to the instance's open session) at the deadline, and the owner's request 30 minutes later, withdrawn when what it reports ends (§6.23)
