### Fixed

- CLI: another instance of an agent joined outside a Git clone gets its own state directory,
  `<handle>#<instance>` beside the first, and no longer hits the first instance's credential. A
  clone that already holds a credential refuses before anything is sent: it says to set
  `MAITY_STATE_DIR` for the new instance and no longer suggests `maity resume`.
- CLI: `maity resume` names this instance (`You are <handle>#<instance>`) and lists the other
  active instances, and `maity messages` shows an instance address as `<handle>#<instance>`.
