### Changed

- web: a dashboard page no longer waits for the notification counts
  (`GET /me/notifications?limit=0`) when it is drawn, a switch from another page included. It draws
  with the counts read so far, and the bell, Chat, the switcher and the tabs follow when the read
  answers, the tab title once the page is named. The inbox still reads its list after the counts,
  and only its header draws before. A failed read is still said in the page's notice; a read that
  answers after a later one changes nothing (tsk-hyfqc0sp2bvc).
