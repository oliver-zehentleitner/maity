### Changed

- tools: `tools/overlap.sh` lists the open pull requests over GitHub's REST
  API (`gh api`, every page) instead of `gh pr list`, so it runs where the
  GraphQL API is blocked, as in Claude Code's cloud sessions. The repository
  and its host are still origin's, read from its URL (`--hostname`; a
  loopback proxy stands for github.com). A list of 100 or more is read twice
  and must not change in between; a failing page, a pull request listed
  twice or a list of another shape stops the check with exit 2, never 0.
