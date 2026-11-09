### Changed

- Release workflows no longer rerun the test suites on the tagged commit. `release-hub` and `release-cli` now publish, and `publish-image` on a `v*` tag now builds, only when ci already passed on that commit (`ci-ok` of the push to main). For the hub and its image, hub-mariadb must also have passed, run by main's own workflow, on a commit of main with the same hub files. They wait while those runs are still going (`tools/release_gate.py`, read-only).
- A hand start of hub-mariadb names the commit it tests in its run title (`hub-mariadb hand <sha>`, or `hand head`).
