### Changed

- web: a page load asks the notifications head (`GET
  /me/notifications?limit=0`) beside `GET /bootstrap` instead of after the
  session and `/me` have been answered. Asked before the session is known,
  its 401, 403 or a maintenance window's 503 ends nothing and redraws
  nothing; once the session is read, such a head is asked again the usual
  way. The root and the sign-in, which lead on to another page, ask no head
  of their own. Settings that lead on to **Mine** ask no second head, and
  **Mine**'s own `…/me/settings` starts beside the project's reads; neither
  is taken over by a drawing for another session or account
  (tsk-zf3wd9t5gjab).
