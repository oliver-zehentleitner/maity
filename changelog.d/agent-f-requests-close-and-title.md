### Fixed

- Hub: withdrawing a personal request on `POST …/requests/{id}/withdraw` now writes the addressee's `personal_request_withdrawn` record (§18.1) and keeps the card as it was (§7), as every other close does, and withdraws only an open request.
- Hub: a request filed to a human in person cuts its title to 200 characters, so a change asked in a project with a long name no longer fails on PostgreSQL and MariaDB.
