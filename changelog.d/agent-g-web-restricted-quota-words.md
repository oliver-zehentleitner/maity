### Fixed

- web: the refusal `restricted_quota` (409, a card's restricted text beyond the project's 200, docs/api.md §1.3, §6.4) has its words in `js/errors.js` and the catalog, so `make check` in `web/` passes on main again (tsk-32915t2vs0w4).
