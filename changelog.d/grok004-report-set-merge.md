### Changed

- cli: `maity report` sets `branch.<branch>.merge` to the branch's own name when its upstream
  is the remote's default branch, as `git switch -c <branch> origin/main` leaves it, and the
  remote has that branch, and says so; until now the report compared the head with main's and
  refused (exit 4). Without the branch on the remote it is refused naming `git push -u`, and
  nothing is changed (tsk-8qwmbw5xydpw).
