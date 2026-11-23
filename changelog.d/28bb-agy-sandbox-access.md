### Fixed

- cli: an Antigravity (agy) placement can read the Keep the Why skill the runner delivers.
  Inside agy's sandbox the skill directory was empty, so its files could not be read and
  the session stalled. The skill stays read-only to the agent.
- cli: an Antigravity (agy) placement can write its clone's `.git` from agy's sandbox, so
  `git fetch` and commits work there. The runner's own files under `.git` and the files
  that make git run a program stay closed to the agent.
