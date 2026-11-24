### Security

- hub: an organisation files no invitation request to a suspended account,
  and a `go` on one while the invitee is suspended answers 403
  `account_suspended` and leaves the request open (§6.26).
- hub: one person gets at most ten invitations in 24 hours, a project's
  by handle and an organisation's together; over the count a project's
  inviter gets 429, an organisation's the same 202 with no request filed
  (§3.4, §6.26).
- hub: a public project's Recently shows a decision with its card's
  current title, and a title edit renders the page at once (§16.9).
- hub: the README badge is not served for a project under a moderation
  hold or whose owner is suspended, pending or deleted, or an
  organisation held or deleted (§6.20).
- hub: the stored public Why view is kept only for the project's current
  repository (§16.9).
