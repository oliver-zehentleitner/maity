### Fixed

- hub: `maity-hub owner create --handle` and `quickstart` take a handle only in the hub's own format, 2 to 31 characters, instead of 2 to 63. A longer handle made an account whose projects no `/projects/{owner}/{slug}` path resolved; a longer login name now makes `quickstart` name the account `owner`. The landing page's `profiles` section refuses a handle longer than 31 characters (`invalid`), since no human carries one.
