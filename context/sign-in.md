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

## A device code is 12 characters in three groups of four

**Id:** f74e7ab6-027b-47bc-906a-35e2e1892ec6
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's decision, 2026-10-27; contract in `docs/api.md` §2.6.2
**Revisit when:** codes are typed wrong noticeably more often than before, or a sign-in method without number matching is added
**See:** sign-in.md#a-device-code-approval-uses-number-matching-and-shows-what-the-hub-observed — 4af71207-7635-46b1-a943-72575a7e13dc — as of 2026-10-27

The code shown for "Sign in another device" is 12 characters of
Crockford's base32 (60 bits), shown as `XXXX-XXXX-XXXX`, instead of 8
(40 bits, `XXXX-XXXX`).

**Reason:** the maintainer found eight characters too short to trust at
a glance. The code was already safe against guessing — short-lived,
rate-limited, and useless without the approval and number matching on
the signed-in device — so the length is for the confidence a human
puts in it, kept at a length a phone user still types.

**Rejected alternatives:**
- Keeping 8 characters: technically sufficient, but did not read as
  strong enough.
- 24 characters (six groups): the maintainer's first ask; dropped in
  favour of three groups because six are tedious to type on a phone,
  where the QR code is not always usable.

## Registration verifies the address before an account exists

**Id:** f592cf44-de6c-4eca-b83f-7c4125729373
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's direction in the project chat, 2026-10-23, recorded in `scope.md`; contract in `docs/api.md` §2.7 and §16.4
**Revisit when:** a registration path is added that verifies the address elsewhere (OAuth with a provider's verified address), or pending registrations are found to be abused as stored state
**See:** scope.md#one-codebase-three-ways-to-run-it-alone-at-home-a-teams-own-instance-and-an-open-hosted-instance — 930cc491-24f2-4dbe-94b6-b5b49e7e2fb2 — as of 2026-10-23

`POST /auth/register` creates no account. It stores a pending
registration for at most 24 hours and mails a signed link; the account
is made only when the link is followed and completed. Every request
gets the same `202`, whether or not the address has an account; only
the mail differs. Registration is `closed` by default, and opening it
needs mail.

**Reason:** the maintainer's direction names it — on a team's own
instance the address is verified before an account exists. An
allowlist by domain means nothing if the account exists before anyone
proved the address, and an open instance must not hand accounts to
addresses nobody controls. Making no account before the proof also
keeps handles and rows free of squatters and leaves nothing to clean up.

**Rejected alternatives** (weighed while writing the contract; the
maintainer's direction settled the choice, not each reason):
- An account at once, unusable until verified: every request with any
  address would leave a row and could take a handle, and the
  anti-enumeration answer would have to cover a half-made account too.
- An account usable at once, verified later: defeats the allowlist and
  gives an open instance accounts for addresses nobody controls.
- Completing only in the browser that registered (a pending cookie):
  breaks reading the mail on another device; asking again for the
  password chosen at registration proves the same person instead.

## A second factor for humans starts with TOTP and recovery codes, asked after every first factor; passkeys come later

**Id:** 3ec96221-b8f8-49d4-951f-9cbc9fc39d91
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the maintainer's go on the two-factor sketch and his acceptance of the contract's seven proposed defaults, both 2026-10-25; the contract arbiter's rulings and two review rounds the same day; contract in `docs/api.md` §2.8
**Revisit when:** passkeys (WebAuthn) are taken up, a human CLI login is added, or the second factor is found to be skipped by a sign-in method or by a call that should have asked for it
**See:** sign-in.md#a-sign-in-link-is-only-as-strong-as-the-mailbox--the-hub-says-so-and-makes-a-mail-sign-in-visible-instead-of-claiming-to-stop-it — 7865693c-fe02-4df8-ac9e-ebb1bbf8cf20 — as of 2026-10-25

An enrolled human gives a six-digit code from an authenticator app, or
one of ten single-use recovery codes, after the first factor of every
new session — password, device code or mail link alike — and again
before a short list of sensitive calls (address and password changes,
changes of the factor itself, minting a credential, instance settings).
The instance admin chooses `off`, `optional` or `required_admins`; a
lost factor is reset by the instance admin only when the human confirms
it by mail, or by the operator on the server.

Which parts are confirmed and which are inferred: the factor types, the
three policy values, step-up, agents being unaffected and passkeys
later are the maintainer's go; asking after every first factor, the
device code included, `optional` as the default, the admin reset with
proof by mail and the operator command, good standing after the factor,
the step-up list and window and the limits are defaults this contract
proposed and the maintainer accepted. Every account may enrol, with or
without a password (the arbiter's ruling; the go had named password
accounts). The proof for enrolling, turning the factor off and new
recovery codes is the password re-given within 10 minutes, or, for an
account without one, a session in good standing at least 24 hours old
(the arbiter's ruling after the second review round). The reasons below
are this contract's reading.

**Reason:** TOTP needs nothing from the browser or the operating
system and nothing outside the hub — no relying-party binding to a host
name that a self-hosted instance may change, no SMS gateway — so it
works on every device a human uses with the dashboard, and the
recovery codes cover the lost phone without the operator. Asking after
every first factor, not only after the password, is what closes the
limit the mail-link entry states: an agent that reads its human's
mailbox can obtain a sign-in link, but not the code from the human's
app. The reset needs the human's mailbox as well as the admin so that
neither alone removes a human's second factor.

The proof keeps a fresh session from the mailbox out of enrolment:
otherwise temporary access to the mailbox would install a factor of its
holder's choosing, which gives good standing at the next sign-in and
with it the power to end the human's trusted sessions — and on a
password account would lock out the human who holds the password.
How an account without a password first gains good standing, and so
enrols for the first time, is left to the accounts design (pending): no
such account can exist yet (registration and `maity-hub owner create`
both set a password).

**Rejected alternatives:**
- SMS codes: a paid gateway, stored phone numbers the hub has no other
  use for, and SIM swapping (as in the passwordless entry).
- Any first factor given in the last 10 minutes as the proof (the
  arbiter's first ruling): a fresh mailbox session could then enrol and
  gain standing through its own factor.
- A factor enrolled outside good standing that stays "unconfirmed" and
  gives no standing until a trusted session confirms it (proposed in
  the second review round): the arbiter chose the 24-hour guard
  instead, which keeps such a factor from being installed at all; an
  account without a trusted session that old waits.
- An exception letting a passwordless human with no session in good
  standing enrol from the session at hand (offered after the third
  round, first for `required_admins`, then generally): before the first
  enrolment such an account never has a session in good standing, so
  one stolen sign-in mail could enrol a factor, reach good standing
  with it, lock the human out and, after 24 hours, move the address;
  withdrawn by the arbiter after the final review.
- Accepting that a mailbox session enrols a factor that gives standing:
  it turns the stated mailbox limit into a takeover of the trusted
  sessions.
- A code by mail as the second factor: mail is already a first factor
  (§2.6.3), so for a mail sign-in both factors would be the same
  mailbox.
- Passkeys first: not rejected, scheduled as the second stage in the
  maintainer's go; TOTP comes first because it has no browser or host
  dependency (reason inferred).
- Asking only after the password, leaving the device code and the mail
  link as they are: the mail link would stay a way around the factor
  (reason inferred). The device code was a close call, since its
  approval already comes from a signed-in device; the maintainer
  accepted asking after it too.

## An instance may make mail the second factor for everyone; then the sign-in link is off as a first factor

**Id:** 04a233ef-5d92-43f3-a3b6-0421171027f8
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's request on 2026-10-31 (a magic link by mail after every sign-in, switched on in the instance settings) and his go the same day on five proposed defaults; contract in `docs/api.md` §2.8.8
**Revisit when:** passkeys arrive and could replace mail as the factor for everyone, or mail outages lock humans out in practice
**See:** sign-in.md#a-second-factor-for-humans-starts-with-totp-and-recovery-codes-asked-after-every-first-factor-passkeys-come-later — 3ec96221-b8f8-49d4-951f-9cbc9fc39d91 — as of 2026-10-31

The setting `second_factor: email` asks every human for a second factor
at every sign-in without anyone enrolling: after the password or the
device code, the hub mails a link and a six-digit code to the verified
address, and only that completes the session. The five defaults, all
confirmed: every new session of every human; TOTP where enrolled
instead of mail; sign-in links by mail off as a first factor while it
holds; step-up by a code by mail for humans without TOTP; switchable
only with complete mail settings and a mail that arrived, with TOTP
and the environment as the way back in when mail fails.

**Reason:** TOTP protects only those who enrol; the maintainer wants a
factor for everyone on an instance without asking each human to set up
an app. Mail is what every account already has, verified at
registration. Turning the sign-in link off is what answers the earlier
entry's objection to a code by mail (both factors would be the same
mailbox): with the link off, the first factor is always the password or
a device approved on a signed-in device. The rest of the shape is this
contract's reading: the link works only in the browser that did the
first factor, so whoever holds the password cannot get the human to
complete the attacker's sign-in with a click; the switch-on mails the
admin a code, because a server accepting a test mail (§16.3) does not
show that mails arrive; a mail outage fails closed rather than falling
back to no factor.

**Rejected alternatives:**
- Mail as the second factor with the sign-in link left on: for a mail
  sign-in both factors would be one mailbox (the earlier entry's
  objection); proposed as rule 3 and confirmed.
- Mail instead of TOTP for everyone: TOTP is the stronger factor (an
  agent reading the mailbox cannot read the app); proposed as rule 2
  and confirmed.
- A link that confirms the sign-in from any device, as a device-code
  approval does: one careless click on a phone would complete a sign-in
  started by whoever holds the password (this contract's reading).
- Falling back to no second factor while mail is down: silently weaker
  than the setting promises (this contract's reading).
- The mail factor giving good standing: it is the mailbox, which good
  standing exists to distrust (§2.6.5; this contract's reading).

