### Changed

- cli: `maity runner` offers a supervised (headless) placement no tool for asking the person at
  the terminal, which nobody answers there: Claude Code gets `AskUserQuestion` as a bare deny
  rule, and Codex gets `[tools.experimental_request_user_input] enabled = false`. Interactive
  placements are unchanged.
