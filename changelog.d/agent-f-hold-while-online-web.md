### Added

- web: the dashboard tells the hub you are present, so the mail of an immediate notification waits while you use it (§18.4, §18.5). A tab sends `POST /me/presence` at once and then every 60 seconds while it is visible and had pointer, key, scroll or focus input within ten minutes, and stops on sign-out or when the session ends. Notification settings → Mail has the switch **No mail while I'm online in the web app** (`email.hold_while_online`, on by default).
