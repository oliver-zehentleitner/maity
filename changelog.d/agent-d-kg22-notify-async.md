### Changed

- web: a dashboard page no longer waits for the notification counts
  (`GET /me/notifications?limit=0`, about 2 s on prod). It draws with the counts read so far, and
  the bell, Chat, the switcher, the tabs and the tab title follow when the read answers. A failed
  read is still said in the page's notice (tsk-hyfqc0sp2bvc).
