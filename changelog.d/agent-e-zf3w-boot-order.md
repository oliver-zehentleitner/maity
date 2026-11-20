### Changed

- web: a page load asks the notifications head (`GET
  /me/notifications?limit=0`) beside `GET /bootstrap` instead of after the
  session and `/me` have been answered. Asked before the session is known,
  its 401 or 403 ends nothing; once the session is read, such a head is
  asked again the usual way. Settings that lead on to **Mine** ask no
  second head, and **Mine**'s own `…/me/settings` starts beside the
  project's reads (tsk-zf3wd9t5gjab).
