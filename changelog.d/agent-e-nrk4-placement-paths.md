### Security

- cli: under a runner placement, `maity files get` saves a file only inside the runner's clone,
  outside its `.git`, never through a symbolic link on the way and never over an existing
  file, `--force` included; every name is opened through the directory before it. Outside a
  placement nothing changes.
- cli: under a runner placement, the git maity starts and the record `maity gh` reads are taken
  from the runner's own directory for the agent, no longer from the clone's `.git/maity`
  (Codex, whose `maity` runs inside its sandbox, keeps them there). A session started by an
  older runner needs a restart of its placement.
