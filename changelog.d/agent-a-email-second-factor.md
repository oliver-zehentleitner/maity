### Added

- docs/api.md §2.8.8: an instance may make mail the second factor for everyone
  (`second_factor: email`): after the password or a device code the hub mails a link and a
  six-digit code to the verified address, and only that completes the sign-in; the link works only
  in the browser that signed in. TOTP stays the factor for whoever enrolled it, sign-in links by
  mail are off as a first factor while the setting holds, a step-up without TOTP asks for a code by
  mail, and turning it on needs a code mailed to the admin (`POST
  /admin/settings/sign-in/second-factor-email/confirm`); a mail outage fails closed.
