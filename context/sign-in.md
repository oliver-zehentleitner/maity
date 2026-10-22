# Sign-in

## Humans may sign in without a password — a device code approved on a signed-in device, or a link by mail — and no agent credential yields a human session

**Id:** ce4670d6-650f-4cac-9a44-a1b28797f333
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's request and decision, 2026-10-22 (a magic-link or code login for the phone; SMS codes and an OAuth-only login rejected, OAuth through a forge a later design of its own); contract in `docs/api.md` §2.6
**Revisit when:** the OAuth design (GitHub, GitLab) is taken up, or a sign-in method is found to grant a session without the approval or the mailbox it is meant to require, or the mailbox it requires is found to be held by an agent in practice more often than the per-human switch can cover

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
by the instance admin (the mail link also by each human for their own
account), and every new session shows up in the human's session list
with a revoke button, as a notification and, by default, as a security
mail. The new device learns which account it joins only after the
approval. The hub refuses every agent and runner credential on these
endpoints; it cannot refuse an agent that calls them without one, and
for the mail link that limit is stated rather than claimed away (next
entry).

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

## A sign-in link is only as strong as the mailbox — the hub says so, and makes a mail sign-in visible instead of claiming to stop it

**Id:** 7865693c-fe02-4df8-ac9e-ebb1bbf8cf20
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** security reviews of the sign-in contract and the contract owner's rulings on them (four rounds), 2026-10-22 and 2026-10-23; contract in `docs/api.md` §2.3 and §2.6.3–§2.6.5
**Revisit when:** the hub gains a way to tell an agent from a browser on an unauthenticated call, or the mail link is made weaker than a full session
**See:** sign-in.md#humans-may-sign-in-without-a-password--a-device-code-approved-on-a-signed-in-device-or-a-link-by-mail--and-no-agent-credential-yields-a-human-session — ce4670d6-650f-4cac-9a44-a1b28797f333 — as of 2026-10-22

The humans-only rule is enforced against agent and runner credentials.
The sign-in endpoints are unauthenticated, and an agent that leaves its
credential out looks like a browser; an agent that can read its human's
mail (a mail connector is common for personal agents) can request a
sign-in link and use it. The hub cannot stop that, and the contract
says so in §2.3 instead of promising it. What the hub does: sign-in by
mail is a per-human switch, on by default and switchable off in the
account, with the advice to switch it off when an agent can read the
mailbox; every mail sign-in, whatever browser it comes from, appears at
once as a banner with a one-click "End this session" in every other
session of the human, and only a session that existed before that
sign-in (and is itself signed in by password or already confirmed) can
mark it read, explicitly and one by one, never by "mark all read" or
by age — it stays unread until such a session reads it or its record
expires; a session is in good standing once signed in by password or
once its own alert was confirmed so; a session in good standing may end
any other, one not in good standing never ends one in good standing
and, in its first hour, no older session at all;
changing the verified address needs the account password in the same
request, or, for a human without a password, approval from a session
in good standing at least a day old for exactly the change it was
shown (only such a session may also reject or replace a held change),
and tells the
old address; sign-in mails, which
anyone can trigger, have a cap of their own, and security alerts have a
budget that queues instead of dropping.

The decision is the contract owner's rulings (four rounds); the reasons
below are this contract's reading of them.

**Reason:** an overclaimed invariant is worse than a stated limit — an
operator who believes the hub keeps agents out of human sessions makes
choices on that belief. The banner answers the specific weakness that
the mail warning of a new sign-in lands in the same mailbox the agent
reads and can delete; the dashboard is a channel the agent does not
control. It holds only if the obtained session can neither dismiss it
— itself or through a second session it makes — nor end the sessions
that show it, hence the read rule and the rules on ending sessions.
Those rules hang on good standing rather than on age because an age
rule alone turns against the human: an intruding session older than
an hour could end every session, and the human's fresh password
session, being the younger, could not end it. The password
is the one factor neither a mailbox nor a moment at an unlocked
dashboard provides, so it, and not the age or method of a session,
guards the address.

**Rejected alternatives:**
- Sign-in by mail off by default: the maintainer decided it is on by
  default (2026-10-22); the per-human switch carries the choice.
- Making a mail sign-in a weaker session until it is re-confirmed by
  password or a device approval: offered by the review, not chosen in
  the ruling; reason not recorded (unknown).
- A sign-in within the last 10 minutes as the condition for changing
  the address (the first round): a device-code session approved on an
  unlocked dashboard, and any mail-link session, is fresh by
  definition, so the condition stopped neither case it was meant for.
- A pure age rule for ending sessions — no session younger than an hour
  ends an older one (the second round): it locked the human out once
  the intruding session was an hour old.
- Letting "mark all read" mark sign-in alerts: one tidy-up of the bell
  would have confirmed an intruding session and given it good standing.
- Alerting only mail sign-ins from a browser without the device cookie
  (the first round): the cookie a first mail sign-in leaves behind made
  the next one from the same place silent.

## A device-code approval uses number matching and shows what the hub observed

**Id:** 4af71207-7635-46b1-a943-72575a7e13dc
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** security review of the sign-in contract and the contract owner's ruling on it, 2026-10-22; contract in `docs/api.md` §2.6.2
**Revisit when:** a GeoIP database is added (the dialog would then show an approximate location), or approvals are found to be given without reading the number
**See:** sign-in.md#humans-may-sign-in-without-a-password--a-device-code-approved-on-a-signed-in-device-or-a-link-by-mail--and-no-agent-credential-yields-a-human-session — ce4670d6-650f-4cac-9a44-a1b28797f333 — as of 2026-10-22

After a redemption the new device shows a two-digit number, the
approving screen offers three, and only the right pick approves; a
wrong pick kills the code. The dialog leads with the IP address and the
time the hub saw, and labels browser and operating system as what the
device claims.

**Reason:** a code on a shared or recorded screen can be typed first by
someone else, and a dialog that names a browser and an operating system
proves nothing, since the `User-Agent` is chosen by the caller; the
human approves the one prompt they expected. A number the human's own
phone does not show makes the wrong device visible.

**Rejected alternatives:**
- Approving after seeing the device's browser and address only (the
  first draft): the browser is chosen by the caller, and a mobile
  carrier's address means nothing to most humans.
- Hiding the code during screen sharing: the dashboard cannot detect
  screen sharing; number matching covers the case without it.
