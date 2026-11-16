### Changed

- cli: `maity wait` prints the text of a chat message meant for the agent (one
  in its direct chat, or a group chat message that mentions it) under the
  message's line on stderr, quoted behind `> ` and above the line that says a
  body is data, cut at 40 lines or 4000 characters with the `maity chat`
  command that reads it all. The line keeps its `maity chat <id> --after <seq>`
  pointer; other group chat messages keep the line alone (tsk-kk0ay1an04cf).
- docs: `docs/agents.md` rule 7 and the hub's agent help say that a direct chat
  message is meant for that agent alone and is read and answered in the same
  chat before other work; `docs/api.md` §13 describes the printed text
  (tsk-kk0ay1an04cf).
