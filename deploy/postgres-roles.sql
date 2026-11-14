-- The hub's two database roles, set up by the superuser in the hub's database (docs/install/README.md, "Database roles"):
--   maity_owner  owns the database and every object of the hub in it; the migrate step logs in with it. No superuser, cannot
--                create databases or roles.
--   maity_app    the running hub: reads and writes rows (SELECT, INSERT, UPDATE, DELETE, sequences), and nothing else. It cannot
--                create, alter or drop a table.
-- The superuser stays for admin work and restores. Run with psql, with ON_ERROR_STOP, the two passwords set first and the script
-- on standard input, so that no password is on a command line:
--   { printf "%s '%s'\n" '\set owner_password' "$(cat owner-password)" '\set app_password' "$(cat app-password)"
--     cat deploy/postgres-roles.sql; } | psql -X -v ON_ERROR_STOP=1 -U maity -d maity
-- It can run again: an existing role gets the attributes again, and the password given now. Without passwords it runs only
-- when both roles exist, and keeps their passwords: that is the run after a restore, which hands to maity_owner whatever the
-- dump brought back owned by the superuser and grants maity_app its rows again
--   psql -X -v ON_ERROR_STOP=1 -v after_restore=1 -U maity -d maity < deploy/postgres-roles.sql
-- With after_restore set it does nothing where neither role exists (an installation that has not moved to the two roles).
-- On a database the hub already used with one role, it hands every object of the hub to maity_owner and grants maity_app its
-- rows (the upgrade path in the same section).
\set ON_ERROR_STOP on
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'maity_owner') AS create_owner,
       NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'maity_app') AS create_app \gset
SELECT :'create_owner'::boolean AND :'create_app'::boolean AND :{?after_restore} AS nothing_to_do \gset
\if :nothing_to_do
\echo 'neither maity_owner nor maity_app exists: nothing to hand over after the restore'
\quit
\endif
-- A role to create needs its password; a missing one stops the script with an error, before anything changes.
SELECT (:'create_owner'::boolean AND NOT :{?owner_password}) OR (:'create_app'::boolean AND NOT :{?app_password}) AS missing_password \gset
\if :missing_password
DO $$ BEGIN RAISE EXCEPTION 'set owner_password and app_password first (\set owner_password ...): a role to create needs one'; END $$;
\endif
\if :create_owner
CREATE ROLE maity_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'owner_password';
\else
ALTER ROLE maity_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\if :{?owner_password}
ALTER ROLE maity_owner PASSWORD :'owner_password';
\endif
\endif
\if :create_app
CREATE ROLE maity_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS PASSWORD :'app_password';
\else
ALTER ROLE maity_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
\if :{?app_password}
ALTER ROLE maity_app PASSWORD :'app_password';
\endif
\endif

BEGIN;
-- The database and its schema `public` (owned by pg_database_owner since PostgreSQL 15) belong to maity_owner, so the
-- migrations can create in it; nobody else can, and only the two roles (and superusers) can connect.
SELECT format('ALTER DATABASE %I OWNER TO maity_owner', current_database()) \gexec
SELECT format('REVOKE ALL ON DATABASE %I FROM PUBLIC', current_database()) \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO maity_app', current_database()) \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO maity_owner;
GRANT USAGE ON SCHEMA public TO maity_app;

-- An install from before the two roles: its objects belong to the superuser. Tables (their indexes, constraints and the
-- sequences of their columns go with them), then the remaining sequences, views and types, then functions, then large
-- objects: the hub writes none, but one in the database would make a dump as maity_owner fail, since it cannot read it.
DO $$
DECLARE r record;
BEGIN
  FOR r IN SELECT c.oid::regclass AS name, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'f') AND c.relowner <> 'maity_owner'::regrole LOOP
    EXECUTE format('ALTER TABLE %s OWNER TO maity_owner', r.name);
  END LOOP;
  FOR r IN SELECT c.oid::regclass AS name, c.relkind FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('S', 'v', 'm') AND c.relowner <> 'maity_owner'::regrole LOOP
    EXECUTE format(CASE r.relkind WHEN 'S' THEN 'ALTER SEQUENCE %s OWNER TO maity_owner'
                                  WHEN 'v' THEN 'ALTER VIEW %s OWNER TO maity_owner'
                                  ELSE 'ALTER MATERIALIZED VIEW %s OWNER TO maity_owner' END, r.name);
  END LOOP;
  FOR r IN SELECT t.oid::regtype AS name FROM pg_type t JOIN pg_namespace n ON n.oid = t.typnamespace
           WHERE n.nspname = 'public' AND t.typtype IN ('e', 'd', 'r', 'm') AND t.typowner <> 'maity_owner'::regrole LOOP
    EXECUTE format('ALTER TYPE %s OWNER TO maity_owner', r.name);
  END LOOP;
  FOR r IN SELECT p.oid::regprocedure AS name FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public' AND p.proowner <> 'maity_owner'::regrole LOOP
    EXECUTE format('ALTER ROUTINE %s OWNER TO maity_owner', r.name);
  END LOOP;
  FOR r IN SELECT m.oid FROM pg_largeobject_metadata m WHERE m.lomowner <> 'maity_owner'::regrole LOOP
    EXECUTE format('ALTER LARGE OBJECT %s OWNER TO maity_owner', r.oid);
  END LOOP;
END
$$;

-- The running hub's rights: on what exists now, and on what the migrations create later (as maity_owner).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO maity_app;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public TO maity_app;
ALTER DEFAULT PRIVILEGES FOR ROLE maity_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO maity_app;
ALTER DEFAULT PRIVILEGES FOR ROLE maity_owner IN SCHEMA public GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO maity_app;
COMMIT;
