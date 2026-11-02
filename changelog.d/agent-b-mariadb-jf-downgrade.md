### Fixed

- hub: the downgrade of `20261031190604_jour_fixe_series` no longer fails on MariaDB, where it dropped an index a foreign key needs and left the database half-migrated.
