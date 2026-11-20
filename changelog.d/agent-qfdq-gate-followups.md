### Fixed

- ci: the test that holds each commit of the release gate's MariaDB job
  table to the commit that added the job ran nowhere: the changelog job
  checks out one commit and the test skipped. The job now fetches those
  commits, and on GitHub Actions a missing one fails the test.
- hub: the reserved-word test takes `sa.schema.conv("vector", True)` as
  quoted; it read only `conv`'s name and reported it unquoted.
