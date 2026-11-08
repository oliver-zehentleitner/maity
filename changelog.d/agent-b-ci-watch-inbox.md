### Added

- `tools/ci_watch.py run --inbox <member id>`: an author who cannot reach the queue file (a cloud session) sends
  the watcher's identity `ciwatch <pr> <full head sha>` as a Maity message. The watcher adds the line with the
  sender as the author once the pull request is open with that head, and answers each request once, added or
  why not. Other messages get no answer. What was read and answered is kept in `<queue>.intake`, so a failed
  answer is said again without watching the head twice.

### Changed

- `tools/ci_watch.py run`: a queued pull request that no longer exists is reported and removed instead of
  being retried.
