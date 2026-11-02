### Fixed

- hub: on MariaDB a refused downgrade stays at the refusing revision, so the same downgrade can run again once the refusal's cause is gone; before, the recorded revision named a schema already undone and the next attempt failed with `1051 Unknown table`
