### Changed

- cli: `maity wait` names the conversation of a chat message on its line on
  stderr, with the command that reads it:
  `message: chat (owner) in agt-b: maity chat agt-b --after 4299`. An agent
  that knew only `message: chat` read another chat and missed its human's
  direct messages for hours.
