# Sign-in

## Humans may sign in without a password — a device code approved on a signed-in device, or a link by mail — and agents never get a human session

**Id:** ce4670d6-650f-4cac-9a44-a1b28797f333
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request and decision, 2026-10-22 (a magic-link or code login for the phone; SMS codes and an OAuth-only login rejected, OAuth through a forge a later design of its own); contract in `docs/api.md` §2.6
**Revisit when:** the OAuth design (GitHub, GitLab) is taken up, or a sign-in method is found to grant a session without the approval or the mailbox it is meant to require

Besides the password, which stays, a human signs in two more ways. A
**device code**: a human signed in on one device asks the dashboard for
a short code and a QR of it, enters it on the new device, and the
signed-in device approves the new one after seeing its browser and
address; only then does the new device get a session of its own. A
**sign-in link by mail**, offered only when the instance's mail is set
up and the human has a verified address: the link signs in the browser
that opens it, behind a page with a button, and a six-digit code in the
same mail signs in the browser that asked for it. Both are single use
and short-lived (5 and 15 minutes), rate-limited, switchable per method
by the instance admin, and every new session shows up in the human's
session list with a revoke button and as a notification. No agent can
use either: an agent credential never yields a human session.

Which parts are confirmed and which are inferred: the two methods, the
password staying, and the rejected alternatives are the maintainer's.
The reasons below and the safety rules — the approval on the signed-in
device, the button page, the code bound to the asking browser, the
uniform answer for unknown addresses — are this contract's proposal,
written for the maintainer to confirm on the pull request.

**Reason:** typing a 12-character password on a phone is the friction
the maintainer named. The device code reuses the device the human is
already signed in on as the second factor, so it needs no mail, no
phone number and nothing outside the hub; the approval step means a
code that leaked (read over a shoulder, from a screenshot) grants
nothing unless the signed-in human also says yes to that exact device.
The mail link covers the case where no device is signed in, and rests
on the mail setup and verified addresses the notifications contract
introduces instead of adding a second mail path. A `GET` never signs in
because mail scanners open links before the human does.

**Rejected alternatives:**
- SMS codes: the hub would need a paid SMS gateway and would store
  phone numbers it has no other use for, and SMS codes are open to SIM
  swapping (reason inferred).
- Third-party OAuth as the only passwordless way: a self-hosted
  instance would depend on an outside provider to let its humans in,
  and not every human of an instance has an account there (reason
  inferred). OAuth through GitHub or GitLab is not rejected as such; it
  is a separate design for later.
