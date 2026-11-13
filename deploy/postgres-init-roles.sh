#!/bin/sh
# Run by the postgres image on a new volume's first start (/docker-entrypoint-initdb.d), as the
# superuser: the hub's two roles from postgres-roles.sql. The passwords go to psql on standard
# input, never on a command line. A volume from before the two roles never runs this: see
# docs/install/README.md, "Database roles", for its upgrade step.
set -eu
{
  printf "%s '%s'\n" '\set owner_password' "$MAITY_DB_OWNER_PASSWORD"
  printf "%s '%s'\n" '\set app_password' "$MAITY_DB_APP_PASSWORD"
  cat /maity/postgres-roles.sql
} | psql -X -q -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
