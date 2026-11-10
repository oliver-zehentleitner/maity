### Added

- web: sign in another device (profile menu, `#/account/sign-in-device`): a code in two groups, a QR
  of its URL made in the dashboard's own code, the time left, and the approval that leads with
  what the hub saw, labels what the device claims, and has you pick the number it shows (Deny is
  the default; no plain Approve)
- web: the login page offers "Have a code?" and "Email me a sign-in link" where the hub has them
  on (`GET /auth/methods`); the QR's URL opens the code form filled in
