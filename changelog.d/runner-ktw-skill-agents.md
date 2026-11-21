### Added

- cli: `maity runner` now delivers the Keep the Why skill in the `agent_user` layout and on ssh
  hosts too. The runner fetches and checks its own copy as before, then puts the same files below
  the agents' user's home (`~/.local/share/maity-runner/skills/`) through `skillop put` (on an
  ssh host the host's own `maity runner skillop`), and checks that copy against the hash it
  recorded at every start (`skillop check`). The session's rules point at it unchanged:
  readable, never writable from the session. A copy that cannot be put or checked starts the
  session without the skill, reported as `keep_the_why_unavailable` (tsk-7casfxb7cn49).

### Changed

- cli: upgrade note for ssh hosts: a host's `maity` needs this version for the skill ops. Until
  it is updated, placements there start without the skill and report `keep_the_why_unavailable`;
  they are not refused.
