### Added

- hub: the account mails of registration (§2.7.5): "Your Maity account is approved" with the
  login link and the person's `registration_approved` account record; on a rejection the
  operator's reason; on an expiry "was not approved in time". All are security mail (§16.2),
  queued in the decision's transaction
- hub: the invitation's mail (§3.4, §18.5): an address-bound invitation is mailed when mail is
  complete and enabled, with the inviter's display name, the project, trust and role, the note
  and the link, on the recipient's security budget; without mail nothing is queued and the
  inviter passes the link on
