### Fixed

- ci: the MariaDB run (`hub-mariadb.yml`) also starts after every push to main, from the last job of `ci.yml`, because GitHub's schedule skipped hours; the hourly clock stays as the fallback, a hand start never counts as the last green run, and a `ci-red` issue closes only when the green commit contains the red one.
