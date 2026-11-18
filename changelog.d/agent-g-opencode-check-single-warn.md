### Security

- cli: `maity runner check` warns that the opencode harness has no OS
  sandbox, on both the local and the ssh backend: under `layout = "single"`
  an opencode agent runs as your own user and can run any command as it,
  including reading the runner's state, the other clones and logins; on an
  ssh host (or any non-single layout) the generic reach is named instead
  (docs/runners.md#opencode-grok, tsk-nynpvag9zvhh). The ok line with
  opencode's path and version stays.
