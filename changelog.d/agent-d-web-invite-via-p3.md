### Changed

- web: the invite form uses the session the page has read (`M.api.session()`) instead of reading
  `GET /auth/session` again; the fixture hub's machine form lists `POST …/invitations` plainly
  again (#684 review).
