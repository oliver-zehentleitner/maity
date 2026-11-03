### Fixed

- hub tests: the notification mail tests start at 12:10 UTC whatever the time of day, so a test that moves the clock by an hour no longer crosses the default digest time (08:00) and fails when CI runs shortly before it.
