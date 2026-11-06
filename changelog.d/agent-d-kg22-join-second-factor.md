### Fixed

- web: in German, a refusal that needs the second factor or the password is said as that, not as missing rights. The dashboard has words for `second_factor_required`, `second_factor_enrolment_required`, `step_up_required` and `reauthentication_required` (`docs/api.md` §1.3). A `forbidden` whose reason has no words yet keeps the reason in brackets instead of the bare "Dafür fehlen dir die Rechte." English readers see the hub's own message, as before.
- web: a test that Join an agent on Your agents (`/agents`) asks for the second factor, as the project's Agents page does.
