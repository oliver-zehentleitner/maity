### Changed

- ci: all pushes to main share one concurrency group and none is cancelled while it runs, so at most one main run runs and one waits (the newest); pull requests are unchanged.
