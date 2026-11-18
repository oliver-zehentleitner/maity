### Fixed

- cli: an opencode placement without a model now starts on the harness
  `default_model`, passed as `--model`, instead of opencode's own free
  default; the start log names the model in effect.

### Security

- cli: the opencode adapter fails closed on the model — an effective model
  that is empty or not among the configured `models` refuses the start
  (`harness_refused`), rather than letting opencode run its own default. A
  provider-`opencode` model is opencode-hosted, so running one would send
  the clone's conversation to opencode's servers instead of the configured
  provider.
