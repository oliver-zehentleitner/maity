### Added

- `maity resume` says "Model changed: X -> Y, your lead is told." after an own change of model, and `maity wait` shows a `session_model_changed` event as `harness/model -> harness/model`.

### Fixed

- A resume that omits `harness` keeps the previous session's, as one that omits `model` does, so a switch from one harness to another across such a resume is announced.
