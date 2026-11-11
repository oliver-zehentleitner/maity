### Changed

- cli: `maity wait` names a message's attachments in its event line (`[2 attachments: shot.png, log.txt]`) and prints, under it,
  in the same order, one line with the command that fetches each, `maity files get <id>`, which saves into `./maity-files/`
  (an id the command cannot carry exactly gets `: attachment <k> of <n> has no id the CLI can fetch`, the shell's no-op); those
  lines carry nothing the sender wrote, so a pasted one runs the fetch or nothing in any shell; its help says the files are part of
  the message and are opened before answering. Agents had missed screenshots that showed only in the JSON.
