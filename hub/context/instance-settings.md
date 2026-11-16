# The instance's settings in the admin area

## A read-only route of its own lists every MAITY_* setting, secrets only as set or not set

**Id:** cb544480-3808-4eb6-8ee0-3930a613129f
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-f87sx61wbfdj (the project owner's wish of 2026-11-15, after deploy 10 showed the agent firewall and the sealing of verifiers only in the startup log); the lead's answers to the design, 2026-11-16; docs/api.md §16.14
**Revisit when:** the hub reads settings from somewhere other than its environment (a config file, the database for more than the admin-set sections), or an instance gets more than one admin role

An instance admin sees in the admin area how the hub is configured: `GET /admin/instance` lists the
version, the schema revision and every `MAITY_*` setting the hub reads, with its value and whether the
environment set it or it is the default. Every setting, not only the on/off switches: a pool size or a
limit is just as much what an admin needs to know at a glance. Nothing can be switched there; the
environment (or the chart) stays the one place a setting is changed, and the hub reads it at start.

A secret never leaves the hub: keys, passwords, tokens, user names and every URL that can carry
credentials answer `value: null` with `set: true|false`, not even a host; a `_FILE` variant is as secret
as what it holds, and when it is unclear whether a value can carry a credential it counts as secret.
The admin needs to know that the key is there, never what it is.

**Rejected alternatives:**
- Adding the settings to `GET /health`: `/health` is public and answered to orchestrators, and must not
  tell anyone how the hub is configured.
- Only the on/off and mode switches: an admin who sees the firewall but not the pool size or the limits
  still has to read the deployment.
- Showing a URL's host while hiding its password: the lead's rule is none of it; one rule for every
  secret is simpler to keep than a parser per URL form.
- A switch in the overview: two places to change a setting, one of them losing at the next start,
  would only mislead.
