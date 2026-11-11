### Fixed

- ci: seven places in the hub tests, reached by eleven tests, drove the app on a fresh event loop (`asyncio.run`, or an unentered test client). On MariaDB the async engine's pool then pinged an aiomysql connection opened on the test client's loop ("attached to a different loop"), and `hub-mariadb` failed (#1649). They now run on the client's own loop (`tests/flow.drive`). The hub itself was not affected: it runs one loop per process.
