### Fixed

- docs: `cli/README.md` says what the CLI, runner and hub do (truth sweep L2b). The resume
  example matches today's output; the jour fixe routes sit under `…/jour-fixe/`;
  `maity api … --json` takes a file; under a placement `maity files get` never replaces a
  file and refuses `-o -`; a guest writes no memory; exit code 4 is any local refusal; an
  `agent_user` runner under the shipped systemd unit needs `NoNewPrivileges=yes` removed;
  and the runner's join, `check`, tmux socket, git and submodule notes match the code.
