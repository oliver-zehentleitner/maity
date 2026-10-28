### Added

- hub: the registration's link page `/mail/register/{token}` (`docs/api.md` §2.7.1 steps 5 and 6,
  §2.7.2): a `GET` that shows the form (the password chosen at registration, handle, display
  name and, when the instance has terms, their acceptance) and changes nothing, a `POST` that
  makes the account, signs this browser in and answers `303` to the stored `next` or the pending
  page. It sets only the `maity_form` cookie before the `POST`, needs that cookie's value in the
  form and a `Sec-Fetch-Site` of `same-origin`, binds the terms version the person saw to the
  registration, shares the login's limit per source address, and the request log masks the
  token. With this the registration works from the request to a signed-in account.
- hub: the registration's sign-in is made like the login's: the browser's earlier session
  ends, the session has its account record and the password given at the completion
  (`method: "register"` counts as signed in by password), the device cookie is set, and a
  rejected or expired pending account takes everything with it that is keyed to it (sessions,
  records, devices, its notification settings and the address claim, mail state and waiting mail).
