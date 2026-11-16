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
- A field per setting naming the Helm chart's value that sets it: the hub would have to know the
  chart's value names and keep them in step with it; every setting is changed the same way, in the
  environment, and with the chart through its values or `extraEnv`, which the contract says once.
  (This alternative was the author's call at the design; the review found it justified, and the
  review lead confirmed recording it, 2026-11-16.)

## The overview reads the environment the process kept at its start, from one list of entries a test holds to the code

**Id:** 07adcfd3-aaec-42df-8f1f-7b0e335d2579
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-f87sx61wbfdj ("a test that fails when config.py has a switch the overview leaves out, or an explicit, commented exclusion list"); hub/src/maity_hub/settings_overview.py, hub/tests/test_settings_overview.py
**See:** instance-settings.md#a-read-only-route-of-its-own-lists-every-maity_-setting-secrets-only-as-set-or-not-set — cb544480-3808-4eb6-8ee0-3930a613129f — as of 2026-11-16
**Revisit when:** the hub reads a setting under a name it builds at run time, which the test's search for `"MAITY_…"` literals would not find

`Settings.from_env` keeps the `MAITY_*` variables that are set, and the overview answers from that,
never from `os.environ` at the time of the request: the hub reads its environment once, so what the
process kept is what runs, and a test hands a client its own environment without touching the
process's. `settings_overview.ENTRIES` names every setting once, with its group, its default
(a constant of the module that owns the setting where one exists, a function for a derived one),
whether it is secret and which admin section can set it too. Whether a setting counts as set
follows the hub's own parser: most trim, a few read the value as written (`as_written`: the
bind address, the public URL, the web directory, the database URLs, the SMTP password, the forge
token). A test sets each to spaces and holds the flag to what `Settings.from_env` does with it,
once without and once under the S3 store (whose credentials are read only there), so a secret is
shown set exactly when the hub runs with it. A setting that a new mode reads only within that mode
needs that mode's base in the test (`MODE_BASES`), or the binding does not see it. One rule for
all secrets ("set when the raw value is not empty") was tried and dropped in review: it showed a
trimmed key of only a newline as set while the hub ran without it.

The guard test reads every `"MAITY_…"` literal under `hub/src/maity_hub`, not only `config.py`:
mail, registration and the GitHub App read their settings in their own modules. A name found
there that is neither an entry nor in `NOT_LISTED` (each exclusion with its reason) fails, and so
does an entry no code reads any more. A second test holds every entry to a row of
`hub/README.md` (Configuration), the page the overview links to.

**Rejected alternatives:**
- Reading `os.environ` per request: it can differ from what the process started with, and a test
  would have to change the process's environment.
- Deriving each value from the parsed `Settings` fields: the source (environment or default) is lost
  once parsed, and a value would be shown in the parser's form, not as the operator wrote it.
- Scanning only `config.py`: a third of the settings are read elsewhere and would slip through.
