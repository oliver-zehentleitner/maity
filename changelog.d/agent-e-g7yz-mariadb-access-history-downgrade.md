### Fixed

- hub: on MariaDB the downgrade of the access history migration (20261118180000) drops the
  table with its index instead of the index first, which MariaDB refused while the foreign key
  on `human_id` needed it (error 1553).
