### Fixed

- hub: a human's rename withdraws the open transfers of the projects in their namespace, as every change of a project's full name must; the `go` could only have been stale (§6.25).
- hub tests: on a server database a test that needs no schema empties the tables before it downgrades, so a project an organisation owns, left by the test before it, no longer fails it by the order of the workers.
