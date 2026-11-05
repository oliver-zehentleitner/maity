### Changed

- hub: pytest keeps a test's temporary directory only when the test failed
  (`tmp_path_retention_policy = "failed"`), so a passing run does not retain a
  copy of the database template per test.
- ci: the `hub-sqlite` job prints `du -sh /tmp/pytest-of-*` after the suite.
