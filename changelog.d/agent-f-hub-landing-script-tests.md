### Fixed

- hub: the landing tests no longer assume that the hub has no `landing.js`: the page may link the hub's own script (and only it), and the test of the script link sets its own files.
