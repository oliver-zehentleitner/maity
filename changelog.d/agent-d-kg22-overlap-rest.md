### Changed

- tools: `tools/overlap.sh` lists the open pull requests over GitHub's REST
  API (`gh api`, every page) instead of `gh pr list`, so it runs where the
  GraphQL API is blocked, as in Claude Code's cloud sessions. The repository
  is still origin's, read from its URL; a failing page or a list of another
  shape stops the check with exit 2, never 0.
