### Fixed

- web: an address that shows a visitor nothing, such as `/no-such-page-here`
  or an unknown view word under a project, now draws a "not found" page in
  the frame of the sign-in ("does not exist, or it is not public", with
  links to the sign-in, the start page and `/explore`) instead of the
  sign-in form; signed-in readers get the same view inside the app in place
  of "No such view". The hub's answer stays the shell with 200 and
  `noindex`; dashboard routes keep the sign-in (tsk-h1e5zmq1wnhj).
