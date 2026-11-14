### Changed

- hub: every six-digit code (TOTP, the sign-in mail's code, the mail
  factor's code) is read by one rule: spaces ignored, anything else
  that is not six ASCII digits is no code (§2.8.1, §2.8.6). A TOTP code
  with a tab or line break in it is refused like the mail codes already
  were. A device code is read by the shared Crockford rule of `codes.py`,
  which also drops a tab or line break as it drops a space.
