### Added

- hub: the session list (`docs/api.md` §2.6.5) — `GET /auth/sessions`
  (`?ended=true` for the last 30 days), `DELETE /auth/sessions/{id}` (with
  every session it approved; the current one is a logout) and `POST
  /auth/sessions/end-others`, with the rules for sessions not in good
  standing; each session has a public `hss-` id, its method, browser and
  system, the latest address and why it ended. `GET /auth/session` gains
  `session_id`. Agents and runners get `humans_only`. Migration `0027`.
- hub: `GET` and `PATCH /admin/settings/sign-in` (`docs/api.md` §2.6.6),
  `MAITY_SIGN_IN_DEVICE_CODE` and `MAITY_SIGN_IN_EMAIL_LINK`, stored in
  `instance_setting`.
- hub: `POST /auth/login` takes `next` and answers it back, `/` for
  anything but a dashboard route (§2.6.5).

### Security

- hub: a login ends the session the browser presents first (session
  fixation, §2.6.5), and an ended session keeps no address.
