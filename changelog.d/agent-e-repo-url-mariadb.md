### Fixed

- hub tests: `test_the_hub_stores_a_non_github_url_and_never_fetches_it` failed on MariaDB whenever the pool opened a new
  database connection during the test, because its guard against outbound sockets also refused PyMySQL's
  `socket.create_connection` to the test database. The guard now lets only the test database's own host and port through,
  the test empties the pool first so that this happens every time on MariaDB, and a new test checks that every other
  address is still refused and counted.
