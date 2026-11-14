### Security

- hub: notification mail subjects are defanged like the mail body, kept on one line and cut at
  120 characters; the invitation's subject is cut the same way (§18.5).
- hub: a notification mail that still waits in the outbox is dropped when the human is no longer
  a member of a project whose items it carries (§18.5).
