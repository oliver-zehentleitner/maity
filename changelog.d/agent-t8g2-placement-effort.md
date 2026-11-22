### Added

- hub: a placement names its reasoning effort, `effort` (§15.5): `null` for the harness's
  default, or one of the `efforts` the runner advertises for the harness, refused otherwise
  with `harness_not_offered`. Part of the spec like `model`, in `POST` and `PATCH
  …/placements`, the runner's read and the request summary; new report detail
  `effort_unsupported`. Migration `20261121130000_plc_effort` adds the nullable column.
- cli: the runner's harness setting `efforts` (Codex and Antigravity only), advertised only
  when set, so a runner without it keeps a hello every hub takes. Codex gets the effort as
  `model_reasoning_effort` in the placement's own `config.toml`, agy as `--effort`; a start
  whose effort the harness no longer offers is refused (`harness_refused`,
  `effort_unsupported`), never started on the default. `maity placement start --effort`.
