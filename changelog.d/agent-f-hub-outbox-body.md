### Security

- hub: a mail that has left the outbox (sent, failed for good or dropped) loses
  its text and its headers at once, and a row that left before is emptied by the
  next sweep; the text and the unsubscribe header carry the mail's links, so a dump or a backup of
  the table no longer holds a valid link of a mail that is out. The recipient
  and the subject stay for the seven days, as before.
