### Added

- CLI: `maity task restricted show|set|clear` reads and writes a card's restricted text (docs/api.md
  §6.4). `set` takes the text only from a file or stdin (`--file FILE`, `--file -`), refuses a word
  left on the command line without repeating it, and sends the version read just before; a
  `conflict` is not retried and never prints the text.
