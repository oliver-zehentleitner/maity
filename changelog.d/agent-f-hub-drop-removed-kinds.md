### Removed

- hub: the compatibility layer for the notification kinds removed on 2026-10-26 (`card`, `agent`,
  `keep_the_why`, `ticker`, `jour_fixe`, `system`, `registration`). Migration 0084 deletes what
  is stored for them in the notification settings; the error `removed_kind` is gone, and such a
  kind is `unknown` in the bell's `kind` filter, in its mark-read body and in the settings.
