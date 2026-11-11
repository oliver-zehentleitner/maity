### Changed

- cli: `maity wait` names a message's attachments in its event line (`[2 attachments: shot.png, log.txt]`) and prints, under it,
  the command that fetches each, `maity files get <id>`, which saves into `./maity-files/`; its help says the files are part of
  the message and are opened before answering. Agents had missed screenshots that showed only in the JSON.
