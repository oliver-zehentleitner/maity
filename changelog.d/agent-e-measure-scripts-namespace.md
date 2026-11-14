### Fixed

- hub: the measuring scripts `hub/scripts/measure_board.py` and `hub/scripts/measure_wait.py` call the project routes under the project's full name again (`/projects/{owner}/{slug}/…`, §6.25); they stopped at the first request with `404` since the namespace. A test runs `measure_board.py` on a tiny board, so the next route change breaks a test (tsk-yajn11fymc0t).
