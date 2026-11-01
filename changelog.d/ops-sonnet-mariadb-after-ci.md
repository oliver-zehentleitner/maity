### Fixed

- ci: `hub-mariadb.yml` also starts after every finished `ci` run on main, because GitHub's schedule skipped hours; the hourly clock stays as the fallback, and a hand start never counts as the last green run.
