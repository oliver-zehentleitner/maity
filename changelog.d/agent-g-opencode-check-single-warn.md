### Security

- cli: `maity runner check` warns that the opencode harness has no OS
  sandbox, so under `layout = "single"` an opencode agent runs as the
  agents' user and can read the runner's state and the other harnesses'
  clones (docs/runners.md#opencode-grok, tsk-nynpvag9zvhh); the ok line
  with opencode's path and version stays.
