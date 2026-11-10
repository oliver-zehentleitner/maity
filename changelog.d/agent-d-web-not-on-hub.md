### Fixed

- web: a route the hub does not serve (404 or 405) is said quietly where its feature would be and
  not asked again for the page's life: the sessions list (a 405 was red), the notifications (read
  every 15 s regardless), the overview's re-reads, a group chat's link on a hub without group
  chats (was a red error); a file's Delete is not offered on a hub without attachments
