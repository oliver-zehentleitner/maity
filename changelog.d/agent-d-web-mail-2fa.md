### Added

- web: the **second step of a sign-in** (§2.8.2, §2.8.8): a session that owes the second factor
  gets one page, the app's code or a recovery code with TOTP, the mailed code with **Send again**
  under the mail factor (its state in words: sent, rate-limited with the wait, unavailable); the
  mail's link `/sign-in/second-factor/email#<token>` posts its token from the page and, opened in
  another browser, says to open it where the sign-in started; a step-up of a human without TOTP
  under the mail factor mails a code and asks for it
