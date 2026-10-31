### Changed

- ci: the MariaDB hub tests leave the pull request gate and `ci-ok`; `hub-mariadb.yml` runs them at most once an hour on main when hub files changed, opens a `ci-red` issue naming the commit range when red, and can be started by hand for a deploy commit. PostgreSQL and SQLite stay per pull request.
