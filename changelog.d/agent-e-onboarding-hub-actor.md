### Fixed

- hub: when the hub itself ends a seat that a project's `settings.onboarding.check_in_with` names (an account deleted, an organisation's owner removed or demoted, the organisation deleted, a project transferred out of it), the setting goes back to `coordinator` with `by` `{"id": "hub", "handle": "hub", "kind": "hub"}`, and the change goes through; before, it failed with a server error (§6.1).
