### Fixed

- docs: the user and agent docs, the agents' skill and `maity help` say what the code does. Exit
  code 4 is any local refusal; exit 6 is another wait of the same credential; `maity wait`
  prints up to 50 events as an array; `maity files get` saves outside the working tree; a
  human's pause is lifted only by a human with `members:admin`; an idle agent shows online
  until about two minutes after its last call, then away until about two hours after it; a
  project may work in any catalog language; the quiet-agent check restarts at most
  `crash_cap - 1` times (`[limits.restart]`, four by default); agy's `require_sandbox = true` refuses it on
  every host for now; public pages need the operator's switch and include Why; and the
  Settings and All projects lists name Runners.
