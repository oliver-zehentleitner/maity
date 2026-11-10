### Fixed

- hub: a proxy with trust `admin` no longer reads the jour fixe answers (docs/api.md §20.3). `GET …/answers` and the redaction of an answer answered `not_found` only to anyone outside the admin team, and the readers a redacted answer addresses leave a proxy out too; both now use the admin-team test (trust `owner` or `admin`, never a proxy).
