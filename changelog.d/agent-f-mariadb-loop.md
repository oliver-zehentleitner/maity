### Fixed

- ci: `hub-mariadb` is green again (#1649). Six hub tests drove the app on a fresh event loop (`asyncio.run`), and the async engine's pool then pinged an aiomysql connection opened on the test client's loop ("attached to a different loop"). They now run on the client's own loop (`tests/flow.drive`). The hub itself was not affected: it runs one loop per process.
