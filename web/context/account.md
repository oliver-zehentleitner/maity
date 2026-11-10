# Account

## Sessions say what this session may not do before it is tried, and This was me is the only way a sign-in is confirmed

**Id:** 561b77f6-2a12-4352-aa50-36a8aa773fbe
**Type:** decision
**Status:** superseded
**Superseded by:** 0d50b2d4-2841-4510-a204-90d3aa574927
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 (good standing, who may end which, the banner), §2.6.3 (a held address change), §2.6.7 (the dashboard's part) and §18.3; the coordinator's card for the sessions view (tsk-s5yq94v758g4), 2026-10-23; the dashboard's implementation, 2026-10-23
**Revisit when:** the hub serves the session list (the view is built against the mock), or the session view gains a field that says what a session may do
**See:** refresh.md#a-sign-in-or-address-alert-is-never-marked-read-by-opening-it-or-by-mark-all-read — 4c95abfb-95af-4c4d-85e0-6fb1cddfd79f — as of 2026-10-23

The account's Sessions section works out from the list itself what this
session may do: whether it is confirmed (`good_standing`), how old it is,
and how old the other session is. From that it disables **End**, **End
all other sessions**, **Approve** and **Reject** with the reason next to
them, and offers **This was me** only from a confirmed session older than
the sign-in it confirms. The hub's refusals are still said in words when
they come. **This was me** marks the alert read by its id, the one way
§18.3 confirms a sign-in. The held address change sits in the same
section, and the mail sign-in banner is shown at the top of every page of
every other session. The banner stays while the reported session or one
it approved is active, applies the list's rules to its End, and is built
again on every round of the `/me` read while a sign-in alert is unread.
"Confirmed" is said only when the alert is no longer unread afterwards,
because the hub answers 200 for an id it skipped; when the list cannot
be read again the result is said to be unknown. A check each minute
redraws the section when this session crosses an hour or a day of age.

**Reason:** the rules are the hub's, but a button that can only fail
teaches the human nothing about why, and §2.6.7 asks for the disabled
buttons and their words. The list carries everything the rules need. A
sign-in is confirmed by an explicit act or not at all, so the alert's id
is sent only from that button. The address change and the sign-ins are
decided by the same standing and the same age, so they are read in one
place.

**Rejected alternative:** offering every button and showing the hub's
refusal afterwards: it works, but it makes the human try in order to
learn the rule. Confirming a sign-in by opening its alert: rejected in
the entry linked above. Putting the held address change under the
notification settings, where the address lives: those settings carry
the mail, and the decision needs the standing that the sessions section
shows.

## Sessions say what this session may not do, and a sign-in is confirmed by its own call

**Id:** 0d50b2d4-2841-4510-a204-90d3aa574927
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.5 (`POST /auth/sessions/{id}/confirm`, `confirmed_at`, the banner), §18.2 and §18.3, contract PR #1230; the bell card tsk-0kz8v1ff5sgf, 2026-11-03
**Revisit when:** the session view gains a field that says what a session may do
**See:** account.md#sessions-say-what-this-session-may-not-do-before-it-is-tried-and-this-was-me-is-the-only-way-a-sign-in-is-confirmed — 561b77f6-2a12-4352-aa50-36a8aa773fbe — as of 2026-11-03
**See:** refresh.md#the-bell-pins-the-unread-security-alerts-and-mark-all-read-takes-them-only-after-asking — 643600cd-dd61-4291-85d7-025e322f4c81 — as of 2026-11-03
**See:** refresh.md#the-bell-pins-security-alerts-but-no-sign-in-the-notifications-page-lists-the-current-sessions-read-again-when-sessions_rev-moves — 09f74f56-7c6c-4d94-a499-ef804b022f3a — as of 2026-11-04

What the earlier entry says about disabled buttons and their reasons stands. What
changed: **This was me** posts the session's confirm and is offered on an active
session that is not in good standing, where this session may confirm it; an ended
session has none. The unread alerts come from the hub's `pinned` block; one that
reports no session in the list gets **Mark read**, and an id the hub skips is said
with its reason, never called read. The mail sign-in banner follows the sessions:
it stays while the reported session, or one it approved, is live and not in good
standing, whatever the alert's read flag, and is checked again on each counts round
while it is shown.

**Reason:** reading an alert no longer confirms anything (§2.6.5), so the session's own
`good_standing` is what the buttons and the banner must follow. The confirm answers with
the session, so its result is known without reading the list again.

**Rejected alternatives:** marking the alert read as the confirmation, as before: the
contract made reading and confirming two acts. Keeping the banner tied to the unread
alert: marking it read in the bell would take the banner down while the sign-in is still
unconfirmed. Offering This was me on an ended session: there is nothing left to confirm.

**Since 2026-11-04** (09f74f56-7c6c-4d94-a499-ef804b022f3a): `pinned` holds no sign-in, so the
unread alerts listed in this section are only the other security kinds, each with **Mark
read**; no row says its sign-in alert is unread, and the ended sessions stay folded. **This
was me** on an active unconfirmed session is unchanged.

## Signed in, the theme is set in Your account; the header has a theme menu only signed out

**Id:** 4faefa89-4543-48f1-a964-53574a6ded5d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the maintainer's instruction of 2026-10-25, together with the instruction of the same day to put Chat and Notifications buttons where the theme menu was; the dashboard's implementation, 2026-10-25
**See:** rendering.md#the-theme-is-set-on-html-by-a-script-in-head-without-defer-the-dark-tokens-answer-the-system-and-an-explicit-pick — ce73e8de-738e-4a8b-89ac-f98ef7d7ed81 — as of 2026-10-25
**Revisit when:** the theme is kept on the hub per human, or the signed-in header gets room to spare again

The theme menu (System, Light, Dark) shows in the header only on the
pages one sees signed out: the sign-in page and the landing page (the
public swarm page went with the contract #697). Signed in, the header has none; Your account has a
Theme section (on its Settings tab, `/account/settings`; `/account/theme` leads there) with the
same three choices as radio buttons and a line that the choice is kept
in this browser only. It is the same per-browser value either way, so a
pick made signed out holds after signing in.

**Reason:** a signed-in human sets the theme rarely, and the header's
top right is wanted for what is used all the time (chat and
notifications). Signed out there is no account to go to, so the menu
stays there.

**Rejected alternative:** the menu in the header and in the account:
it keeps the place the header needs. Keeping the choice per human on
the hub: a contract change for something a browser holds well enough,
and the instruction asked for none.

## Registration is offered where the hub registers or the invitation one comes from admits

**Id:** f1e41ebd-42a8-484b-b260-f69ee036a00c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.7, §2.7.1 and §3.4; the coordinator's ruling of 2026-10-26 that the registration page is built with the invitation card (tsk-55xeem2xbht5); the dashboard's implementation, 2026-10-26
**Revisit when:** `GET /auth/methods` starts to say something per invitation, or registration gains a way in that is not an address and a password (OAuth, §2.7.1)

`/register` shows its form where `GET /auth/methods` says
`registration: true`, or where its `next` is an invitation whose page
says `registration: sign_in_or_register`. Otherwise it says the hub does
not create accounts on request and leads to sign in. After the request it
always says "check your mail", for every address alike.

**Reason:** under `closed` or `allowlist` an address-bound invitation
admits its address (§3.4), but `GET /auth/methods` keeps the instance's
mode and so says `false`; the invitation's own answer is the only place
the page learns that this person may register. The hub answers every
well-formed request the same, so the page must not suggest it knows
whether an account will be made.

**Rejected alternative:** the form for everyone, the hub sorting it out:
on a closed hub every visitor would fill it in for a mail that never
comes. Only `GET /auth/methods`: an invited person on a closed hub could
not register at all, which §3.4 allows.

## The registration form names the instance's terms before the mail is sent

**Id:** 48c34360-b586-4e82-b21a-737b922f1734
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.6.1, §2.7 and §2.7.2; the card tsk-46vft0764kve (the terms from `terms`), the review of #652, 2026-10-29; the coordinator's ruling on an empty allowlist, 2026-10-29
**Revisit when:** acceptance moves from the link's page to the form, or terms gain more than a URL and a version (§16.4)

Where `GET /auth/methods` answers `terms`, `/register` says that
completing the account accepts this hub's terms, with their version. It
links the terms only when `M.dom.safeUrl` passes the address (plain
`https`, no user info); otherwise it names them without a link. The
hub answers `registration: false` under `allowlist` while both lists
are empty, so neither the login page nor `/register` offers a way in
that nobody could finish; the instance admin sees the gap as
`missing: ["allowlist"]` (§16.4).

**Reason:** the terms are accepted on the link's page, where their
version is signed with the registration token (§2.7.2). Without a word
on the form, a person would meet them only after the mail, and might
find out only there that they do not want to accept them.

**Rejected alternative:** a checkbox on the form: it would record
nothing, since acceptance and its version belong to the completion's
`POST` (§2.7.2), and it would suggest a second acceptance. Linking any
URL the hub returns: the hub checks `https`, but the dashboard does not
rely on that alone. `registration: true` under an empty allowlist, as
the contract first said: every address would get the form and the mail
silence of a request that is dropped, a dead end for everyone.

## A human's picture is set on the account, an agent's in its row on Members; the account keeps only agents no project shows

**Id:** 59aaf51f-c63d-4cb6-966b-85eb8f2c682d
**Type:** decision
**Status:** superseded
**Superseded by:** 1031c11b-7642-4ed9-87ce-de504b2044fc
**Evidence:** confirmed
**Source:** the maintainer's wish on the card tsk-th1yq0jtk3yf (an agent's picture belongs to its management, personal settings keep only one's own), 2026-10-28; the coordinator's ruling on the fallback for agents in no project one is in, 2026-10-28
**Revisit when:** the dashboard gets a page of one's agents outside any project, or §6.10 gives `members:admin` a say over pictures
**See:** rendering.md#a-picture-is-uploaded-on-the-account-checked-as-the-hub-checks-it-with-no-preview-of-the-chosen-file — 3ec853f0-4141-4e81-acdf-c0fee94c920b — as of 2026-10-28

The account's Profile tab (`/account`; `/account/picture` leads there) sets the human's own picture. An
agent's picture is set where the agent is managed: in its row on
Members, under **Details** or **Manage**, for its owner only, as §6.10
allows. The picture is read from one's agent profiles (`GET /agents`)
when the first such row opens, since the member list carries no
`avatar_source`. The account still lists, under **Agents in other
projects**, the owner's agents that are in no project the owner can
open, and only those. `/account/picture/<agent id>` for an agent that
Members reaches leads to `/<owner>/<slug>/team/<agent id>/picture`,
the row open. The checks before sending and the missing preview stay as
the entry this one replaces describes them.

**Reason:** a picture is part of managing the agent, next to its
credentials and rulebook, not of the human's personal settings. An
agent working only in projects its owner is not a member of has no row
the owner can open. Without the account's list, its picture could not be
set from the dashboard, and a Keep the Why notice about it would lead
nowhere.

**Rejected alternative:** dropping the account's list entirely and
sending such a notice to `/all`. `/all` says nothing about the agent,
and its picture would become unreachable. Keeping every agent's picture
on the account: this is what the maintainer asked to move.

## A sensitive call asks for the password or a code where it stands, then is made again

**Id:** bddf61cb-f6a0-4290-891f-2f3b3006946d
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.8.1 (the proof: the password in the last 10 minutes, `reauthentication_required`) and §2.8.4 (the step-up, `step_up_required`, "the dashboard asks for a code and repeats the call"); the coordinator's card for Your data (§2.9), 2026-10-28
**Revisit when:** the hub tells in advance which calls will need a proof, or the dashboard gets a dialog layer of its own

A sensitive call goes through `M.stepUp.run` (`js/step-up.js`). It
makes the call. When the hub refuses with `reauthentication_required`
or `step_up_required`, it asks for the password or a code in a slot of
the section that made the call, proves it (`POST /auth/reauthenticate`,
`POST /auth/second-factor/verify`, a recovery code too) and makes the
call again, at most three times. A wrong answer is said there and asked
again. Cancel ends quietly.

**Reason:** the hub, not the page, knows whether the password was given
in the last 10 minutes and whether the human is enrolled, so asking
only after its refusal never asks for nothing. The question stands next
to the button that caused it. Your data is the first user; the other
sensitive calls (§2.8.4) can take the same helper; the transfer of a
project (Project settings, §6.25, §6.26) does since 2026-10-29, where it
used to say to sign in again.

**Rejected alternative:** asking for the password before every
sensitive call: needless right after a sign-in, and wrong for a
passwordless account. A modal dialog: the dashboard has none, and a
slot in place keeps the focus and the context where the human was.


## Every route that asks for the factor is called through M.stepUp.run, held by a list the hub test and the check share

**Id:** 4dc6b1f0-bd9d-4110-a961-41e830af134e
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-6dk86ej9s0fq (the owner, 2026-11-09: pairing a runner on /runners showed only "This needs your second factor first."; the lead's scope: the fix, an audit of every route that calls `require_step_up`, a guard, the fixture refusing); hub/src/maity_hub (the routes), docs/api.md §2.8.4; the guard's form is the implementer's, as the card left it
**See:** account.md#a-sensitive-call-asks-for-the-password-or-a-code-where-it-stands-then-is-made-again — bddf61cb-f6a0-4290-891f-2f3b3006946d — as of 2026-11-09
**Revisit when:** the hub publishes which routes ask (in its OpenAPI, say), or the dashboard's calls go through typed per-route functions

`tools/step-up-routes.json` lists the hub's routes that ask for the factor (method and path under the API prefix; `body` where the hub asks only for one field, `when` where it asks only in some cases). Three readers keep it true:
- `hub/tests/test_step_up_routes.py` reads the hub's source: every route whose handler reaches `second_factor.require_step_up`, directly, in a lambda it hands on, or through the hub's own functions it calls. Each call is resolved through the module's imports, so the gate imported under another name, or called by a module's name or its full dotted path, counts the same. A function handed around under another variable or taken by `getattr` is not followed. The two sets must be equal.
- `tools/check.py` fails on a call `M.api.<verb>(path, …)` in `js/` whose path it reads as one of those routes and that does not go through `M.stepUp.run`. It is a reading of the text, not of the program. It recognises exactly the forms below; any other form is not checked and can pass.
  - **Path:** the parts of a `+` chain that are a string literal; `ctx.base`; a name, read from the last `const name =` or `let name =` before the call anywhere in the file (not by blocks); a call of such a name bound to an arrow, whose body is read; or `a ? b : c` and `a || b` of those; three deep. Any other part stands for any run of characters, slashes too (`M.api.projectPath` gives several segments). A path with no part read is left alone.
  - **Names in a body and of a named arrow (form 2 below):** a name is bound only by a declaration `const name =` or `let name =`. The check walks out from the call through the `{…}` blocks around it to the nearest block that declares the name, and takes there the last such declaration before the call, else the first. Its value is the text after `=` up to its `;` or the end of its block. Nothing else binds a name for the check, in a path either: not a later declarator after a comma (`const a = 1, name = …`), a parameter, a destructuring, `var`, a function declaration or a reassignment.
  - **Body:** for a route that asks only for one field, the call's body is read with the value of every name in it, three deep. The field counts where its key stands as a word in that text, so a key behind a variable counts.
  - **Asking first**, in exactly these four forms; in 2 to 4 the arrow's body is the call itself (`=> M.api.…(…)`, in parentheses or not), not a block:
    1. Inside the function expression that is the whole of `M.stepUp.run`'s first argument; not one called or bound right there.
    2. In an arrow `const name = (…) =>` or `let name = x =>`, not `async`, where an `M.stepUp.run(name, …)` in the file resolves, by the blocks around it, to this declaration. This shows the binding is handed to the question once, not that every call of it goes through it.
    3. In an arrow that is a property `key: (…) =>`, not `async`, where every `.key` read in the file (`x.key`, `x[i].key`) is `M.stepUp.run`'s first argument, no `{ … key … } =` destructures it, no `["key"]` reads it, and the file makes no call through brackets (`…](`).
    4. As an argument of a local function (`function f(…) {` or `const f = (…) => {`) whose parameter in that place is handed to `M.stepUp.run` as its first argument in its body. `f` is found as follows, and only so: the check walks out from the call through the `{…}` blocks around it to the nearest block that declares `f` by a function declaration (a `function`, also `async` or `export`, where a statement starts: at the top or after `;`, `{` or `}`), a `const` or a `let`. There it takes the last function declaration of that block, wherever the call stands; if the block has none, the last `const` or `let` before the call, else the first. Where that declaration is not such a helper, the call does not ask. Any other binding form is not resolved and can pass, for example a named function expression's own name, a parameter, `var`, an import or an assignment.
  - A call made to work out `M.stepUp.run`'s arguments, or in another of its arguments, is sent before anything is asked, and does not count.
  - `tools/test_step_up_check.py` holds those readings, some through the whole check on a file of its own (tsk-4zrnkb3gh6mq, after xyfr's post-merge re-check of #1547 found that a name given to `M.stepUp.run` anywhere in the file had counted, and 4hch's review of #1566 the reads and names the first fix still missed).
- The same check keeps `js/api.js`'s `STEP_UP_ROUTES` equal to the list. With `window.MAITY_FIXTURE_STEP_UP` set (to `Date.now()`, so that a code given earlier in the run does not count), the fixture hub refuses them with `step_up_required` until a code is verified.

A reject of a held address change is never asked by the hub, but it is sent through the question like the approve: the hub's reading includes it, and asking only after a refusal costs nothing there.

Known limits, each a way a new guarded call could go unseen (tsk-4zrnkb3gh6mq records them rather than closing them):
- The hub test finds routes declared as `@router.<method>("<path>")` on a module-level function with a local `APIRouter`. A route added with `add_api_route` (as `routes/project_images.py` adds its image routes), a class method, or a router built inside a function (as `app.py` builds the one for `/languages` and `/health`) adds nothing to its set; none of those files reaches `require_step_up` today.
- `tools/check.py` follows only the forms listed above. Any other way to write a binding, a path or a hand-over is not checked and can pass: a parameter of the same name, a reassignment, an alias that keeps the arrow, a direct call beside the wrapped one, a function passed under another name, a value stored and read in another file.
- The fixture asks for the factor on any `email.address` in `PATCH /me/notification-settings`; the hub asks only when a verified or disabled address changes (`_change_address` in `hub/src/maity_hub/notifications/preferences.py`). Wider than the hub, it never lets through what the hub refuses.

**Reason:** the runner pairing, the mail settings, the password, the address change and its approval, and the answer that moves a project were each written without the helper, and nothing failed until a person met the refusal. A list read from the hub and a check over every call catches the next one when it is written. A test drives only the flows someone thought of.

**Rejected alternatives:**
- The fixture refusing, with smoke and e2e to catch a missing question: it finds only what a test drives, and none of the eight calls had such a test.
- A hub contract test against routes named in docs/api.md: §2.8.4 names the calls in prose, not as a list a test reads, and the step-up is decided in the hub's code, which the source reading follows.
- Every `M.api` write through `M.stepUp.run`: each form would need a slot for a question the hub never asks.


## The second step of a sign-in is a page of its own for both ways; the mail's link is posted from the page

**Id:** 4fdf4cc1-e916-44d7-9064-5b07989b0d06
**Type:** decision
**Status:** needs-review
**Evidence:** confirmed
**Source:** docs/api.md §2.8.2 (the second-factor session reaches only `GET /auth/session`, the verify, the mail's resend and the logout), §2.8.7 and §2.8.8 after the contract #925 and the hub's first part #943 (`via: email`, `mail`, the link `/sign-in/second-factor/email#<token>` bound to the signing-in browser, the step-up by a mailed code); the coordinator's card tsk-ekpb0pvgw4bh and the lead's answers of 2026-11-01 (the step for both ways in this change, TOTP enrolment and the security page on tsk-94jtz06aps4b; `address_hint` to come with the hub's second part, "your address" until then; Admin → Sign-in in a second web change); the page's shape is the implementer's, 2026-11-01
**See:** account.md#a-sensitive-call-asks-for-the-password-or-a-code-where-it-stands-then-is-made-again — bddf61cb-f6a0-4290-891f-2f3b3006946d — as of 2026-11-01
**Revisit when:** the hub sends `address_hint` (drop "your address"), TOTP enrolment gets its page (tsk-94jtz06aps4b), or the e2e gets a hub with a secret key and a mail catcher

A session that owes the second factor (`GET /auth/session` answers
`second_factor: "required"`) gets one page and nothing else
(`js/second-factor.js`): with `via: totp` a field for the app's code or
a recovery code (six digits, spaces ignored, are a code); with `via:
email` the mail's state in words (sent, to `address_hint` or "your
address"; the next mail's wait when rate-limited; unavailable), a field
for the mailed code and **Send again**, which reads the session again
for what the hub says of the new mail. **Sign out and start again**
ends it. The mail's link lands on
`/sign-in/second-factor/email#<token>`: the page reads the token from
the fragment (the query `?token=` in fixture mode), drops it from the
address and posts it at once. A browser without that session, or one
already signed in, gets the contract's sentence on where to open the
link instead. The step-up asks `GET /auth/second-factor` when the hub
wants the factor: a human whose `via` there is `email` is mailed
a code as the question opens, with Send again, and types it
(`email_code`); everyone else keeps the app's code.
The fixture's verify takes `email_token` at a step-up too, as it cannot
tell the step from the step-up; harmless while the step-up sends only
`email_code` (the hub never takes the token there, §2.8.8). A session
state in the fixture was rejected for that one case.
The e2e's second hub covers the TOTP step and the step-up (#1003), and a
hub of its own the mail: the admin's switch, the link, the code and the
step-up by mail.

**Reason:** the dashboard had no second step at all, for TOTP neither;
both ways run in the same second-factor session, so one page serves
both. The mail's token completes only the sign-in of the browser that
asked for it, so posting it without a tap gives nobody anything; a tap
would only add a step to the one place where the human has just
clicked a link for exactly this.

**Rejected alternative:** a step for the mail alone, leaving an
enrolled human at a session that reaches nothing. A confirm button
before posting the link's token, as the device code has: the device
code approves another browser's sign-in, the token only this one's.
Trying the app's code first at a step-up and falling back to the mail
after a failure: one wrong code counts toward the limit (§2.8.6) and
says nothing a read of `GET /auth/second-factor` does not. The e2e
runs neither way: its hub has no `MAITY_SECRET_KEY`, which TOTP needs
and which the forge step checks is missing, and no mail settings; the
step for both ways, the link, the page elsewhere and the step-up by
mail are in smoke.

## The meat-proxy hint quotes the hub's note as /me carries it, and no text of its own

**Id:** 8eb486bb-357a-477c-aaf5-2a4d51024cc4
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2 `GET /me` ("the dashboard shows it under the switch from here and keeps no copy of its own") and §5.2 "Meat proxy"; the change that replaced the page's own sentence with `meat_proxy_note`; #990 removed the case for a hub without the note
**Revisit when:** the note gets text per human or a translation, or `/me` stops carrying it

Under the switch **I am a meat proxy** the account quotes
`meat_proxy_note` from `/me` as text, never through HTML.

**Reason:** the human should read exactly what the agents that deal
with them read. Any wording of the page's own drifts from the hub's as
soon as the note changes, as it did once already.

**Rejected alternative:** keeping the old sentence as a fallback where
the field is missing: on a hub whose note has changed, it would show
words the agents no longer read, the drift this avoids. Keeping a case
for a hub without the field: no such hub runs under the alpha rule
(§1.6), so #990 removed it.
Copying the text into the page: the same drift with every change of
the wording.

## The meat-proxy switch has its two parts under it, each sent alone; the hub decides the switch and the note

**Id:** e9c14296-f8da-4f83-871b-056a0d3ab6ed
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2 `GET /me`, §5.2 "Meat proxy" and the `PATCH /me` row after the contract #702 (two stored parts, the switch derived, the order in which a body applies); the coordinator's card tsk-j9mgn2z3e7pf (two sub-points, both ticked on switching on, each cleared alone, the note under them from `GET /me`), 2026-10-30; the page's shape is the implementer's, 2026-10-30; the review of #720 (the answer's shape), 2026-10-30
**See:** account.md#the-meat-proxy-hint-quotes-the-hubs-note-as-me-carries-it-and-no-text-of-its-own — 8eb486bb-357a-477c-aaf5-2a4d51024cc4 — as of 2026-10-30
**Revisit when:** the hub adds a third part, or the note gets text per human or a translation

Under **I am a meat proxy** the account shows the two parts, *Lead me
step by step rather than expecting me to explain.* and *When you need a
human's hands, come to me first.*, as checkboxes of their own. The
switch sends `meat_proxy` alone (on ticks both, off clears both); a part
sends only that part, so ticking one while the mode is off turns it on
with that part, and clearing the last turns it off. After every answer
the switch, both parts and the note are drawn from what the hub sent
back, never from what was clicked. The answer of `PATCH /me` is `/me`
itself (§5.1), so the page reads `answer.member`, as it reads `GET /me`;
the fixture hub answers in that same shape. The note stands under the parts;
while the mode is off it is the text switching on would send.

**Reason:** the hub stores the parts and derives the switch, so drawing
from its answer keeps the page and the agents' text the same, whatever
order the person clicks in. Sending the one field that changed lets the
hub's order rule decide, as §5.2 spells it out.

**Rejected alternative:** sending the whole state (switch and both parts)
on every change: `meat_proxy: false` with a part set to `true` is
`invalid`, and the page would have to repeat the hub's rule. Disabling
the parts while the switch is off: the contract lets one part alone turn
the mode on, which a disabled box would hide. Labels of the page's own
wording for the parts: they are the person's own sentences in §5.2, the
same words the note puts together. Reading the fields at the top of the
answer with the clicked value as fallback (the earlier code): against the
hub it never read the answer at all, and the fixture's flat answer hid it.

## Forge access is a section of the account, also at /settings/forge; a project's settings say which grant reads its repository

**Id:** 861705c6-539c-4d4c-9532-658311c463b7
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** the coordinator's card tsk-6pbe89e1yt50 with the maintainer's decision that the hosted instance carries no platform GitHub token, 2026-10-31; docs/api.md §11.4 (links, own token, step-up, the setup redirect to `/settings/forge`, the owner's confirmation), §16.11 (the path), §6.1 (`probe_via`, `owner_confirmed`)
**Revisit when:** installations on a forge organisation may serve a Maity organisation (§11.4 "Follow-up"), or a second forge is added

**Forge access** is a tab of the account's Security
(`/account/security/forge`), next to the sessions. It shows:
- the linked installations of the instance's GitHub App, each with its
  status and the repositories it covers;
- **Link the GitHub App**, offered only where `app_configured`;
- **Unlink**, which says it does not uninstall the App on GitHub and
  links to GitHub's page;
- the human's own fine-grained token: stored, replaced or removed,
  with a hint naming the read permissions the probe needs.

A token is never shown, only that one is set, its login and its status.
`/settings/forge`, the path the hub's setup redirect lands on, shows
that same tab at its own address. Its `?error=<reason>` is said
in words and dropped from the address. A project's settings say which
grant reads its repository (`probe_via` in words) and whether the
namespace owner confirmed it, with **Confirm this repository for my
grants** for the namespace owner (for an organisation's project any of
its owners, who may replace another owner's confirmation with their
own grants) and a link to Forge access.

**Reason:** the grants are the human's own and serve every project they
own, so they belong on the account, not on one project. The project's
settings are where an admin wonders why nothing is read. Without the
owner's confirmation their grants are never used for the repository,
so the confirmation stands next to the grant it unlocks.

**Rejected alternatives:**
- A page of its own at `/settings/forge`: a second "account" with one
  section, beside the account that has all the others.
- Redirecting `/settings/forge` to `/account/forge`: the contract names
  `/settings/forge` (§16.11), and a redirect would add a hop to the
  setup's return.
- Showing the probe's `details.reason` on the settings: it comes from a
  failed read, not from the project view, and the view's `probe_via`
  with the confirmation already says what is missing.

## Two-factor sign-in sits on the account; a session that must enrol gets the setup as its one page

**Id:** ed407146-2c2b-4686-87ef-a5d8e6d020e2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.1, §2.8.5, §2.8.7; the card tsk-94jtz06aps4b; #1004
**Revisit when:** mail as a factor gets a section of its own

A session in `enrolment_required` gets the setup drawn by `render()` like the second-factor step, not routed, so the address asked for stays, often `/`. The secret and the recovery codes live only in the DOM of the step that shows them and go with it; the codes leave the page only by the human's **Download**. Setup, new codes and **Turn off** go through `M.stepUp.run`, as the hub asks for the password or the factor and the page repeats the call.

**Rejected alternative:** a route of its own for the setup: a session in enrolment reaches nothing else, so the page must be the same either way. Keeping the codes until the next visit: §2.8.1 shows them once.

## The enrolment page is guarded only while it is on the page

**Id:** 056d57c5-e0d5-4fc1-83d1-d4042c55dab8
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.5; review of #1004; tsk-xtnxws153a7x

A refusal `second_factor_enrolment_required` draws the setup through `render()`; a flag stops a late refusal from drawing it over itself, which would throw away the secret being typed. `render()` clears the flag and only `renderEnrolment` sets it for good, so it says "the setup is on the page". The first form, cleared only when the setup succeeded, left a tab that signed out, or whose hub let go of the requirement, deaf to the next refusal.

**Rejected alternative:** tying the flag to the session epoch: a hub that releases the same session keeps the epoch, and the tab stays deaf.

## The reset form stays open and names no enrolment state

**Id:** a5c7675b-8785-4a40-b088-b0a0022818c5
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.8.3, §2.8.7; tsk-xtnxws153a7x

Admin → Users offers **Reset two-factor sign-in** on every row but one's own, and the hub's `409 conflict` says when the person has no factor: `GET /admin/users` does not carry whether someone enrolled. The form is one under the list, not one per row, and stays through a search, so the warning to confirm by another channel is read beside the reason, not skimmed in a table cell.

**Rejected alternative:** a confirm dialog: it has no room for the reason and the warning, and a modal is the wrong place for a text someone has to think about.

## The mail address asks for the password beside it, optional, and the hub decides

**Id:** 1f725886-4f1f-47a3-b1cd-a74bf82aedb2
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4 "Changing a verified address" and §2.6.3, the web mail section of tsk-x9g29m2rcx72, 2026-11-02
**Revisit when:** the session or `GET /me` says whether the human has a password

The mail address sits on `/account/notifications`, only where `mail_available` is true;
the personal language above it stays either way. Changing or removing a confirmed address
shows a password field marked "if you have one", and `current_password` is sent only when
something was typed. The hub's `current_password: "required"` or `"mismatch"` is said at
that field. A change the hub holds (`202`, `address_change` naming the address just sent)
is said as waiting, with a link to the sessions on the same page, where it is approved or
rejected; an older held change shown there is not taken for this one.

**Reason:** the dashboard cannot tell whether a human has a password: neither the session
nor `/me` says so, and §18.4 treats the two cases differently (password in the request, or
the age of the session). An optional field covers both, and the hub's answer tells which
case it was.

**Rejected alternatives:** a field in `/auth/session` saying whether a password is set: a
contract change for one hint, and it would tell any script in the page something about the
account's sign-in. Asking for the password always: a human who never set one could not
change the address at all. Never asking and waiting for the refusal: one failed request
on every change of a confirmed address.

## When mail goes out: the page sends only what changed, the browser's zone only offered

**Id:** 444115c8-aaaf-408e-a16c-571aa48f69cf
**Type:** decision
**Status:** superseded
**Superseded by:** 44009d6f-ff99-4f8a-b51e-cb9531702422
**Evidence:** inferred
**Source:** docs/api.md §18.4 "Defaults and what was saved", the web mail section of tsk-x9g29m2rcx72 (#1223), 2026-11-02
**Revisit when:** the hub can reset a kind to its default

The modes and times on `/account/notifications` are compared with the hub's merged answer, and
the `PATCH` names only what differs: in `email.kinds` only the kinds that changed, each with only
its changed part (`mode` or `content`). The time zone is the account's. When the browser reports
another one, a button offers it, but the page never sets it unasked.

**Reason:** the hub stores only what the human set, and a kind it was sent counts as set even if
the value is unchanged. Sending the whole form would pin every kind at today's default, and a
later change of the default (as the digest defaults of 2026-11-02) would no longer reach them. The
zone decides when digests and quiet hours fall; a browser on a trip should not move them.

**Rejected alternatives:** sending the whole `email` object on each save: it pins every default.
Setting the browser's zone when the account still has `UTC`: a person who chose UTC on purpose
would see it changed.

**Known limit:** a mode changed and later set back to the default stays set; the contract has no
reset.

## When mail goes out: the page sends only what changed; the time zone is set under Settings, the browser's only offered

**Id:** 44009d6f-ff99-4f8a-b51e-cb9531702422
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §18.4; the web mail section of tsk-x9g29m2rcx72 (#1223), 2026-11-02; the owner's decision on the account time zone (message seq 94723) and the approved plan on card tsk-j8s6n725a06r, 2026-11-08
**See:** account.md#when-mail-goes-out-the-page-sends-only-what-changed-the-browsers-zone-only-offered — 444115c8-aaaf-408e-a16c-571aa48f69cf — as of 2026-11-08
**Revisit when:** the hub can reset a kind to its default

The modes and times on `/account/notifications` are compared with the hub's merged answer, and
the `PATCH` names only what differs: in `email.kinds` only the kinds that changed, each with only
its changed part (`mode` or `content`). The time zone is no longer a field there: it is the
account's, chosen in Account → Settings, and the mail page names it with a link there, or says
the mails follow UTC while none is set. In Settings the browser's zone is offered first, as a
button and at the top of the list, but the page never sets it unasked.

**Reason:** the hub stores only what the human set, and a kind it was sent counts as set even if
the value is unchanged; sending the whole form would pin every kind at today's default (unchanged
from the earlier entry). The zone now decides every time the dashboard shows as well as when
digests and quiet hours fall, so it belongs with the language under Settings, not under mail
(the owner's decision, confirmed); a browser on a trip should still not move it.

**Rejected alternatives:** sending the whole `email` object on each save: it pins every default.
Setting the browser's zone while the account has none: the dashboard already shows times in it
then, and storing it would turn a guess into a choice the human never made. Keeping a second zone
field on the mail page: two places for one value.

**Known limit:** a mode changed and later set back to the default stays set; the contract has no
reset.

## The account is in tabs, each at an address of its own; the addresses before them lead to their tab

**Id:** 36bfb48e-ae7c-41f4-9e73-b0abfef34bce
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-3banvfzv3nvs (the maintainer and the lead, 2026-11-05): the tabs Profile, Settings, Notifications, Security and Organisations, Linked accounts shown as to come, the profile menu as the tabs, a sideways-scrolling row on a phone, the hub unchanged; Security's own tabs proposed to the lead on the card (2026-11-05); the scroll carried over from the page before, reproduced on main (`/account` opened at 2481 of 4535 px)
**Revisit when:** linked accounts arrive, the hub's mails and redirects name the new addresses, or a tab grows long enough to want tabs of its own

The account page is in tabs (`js/account.js`), each tab at its own address. The profile menu is
the same list as the tabs, followed by Sign out.

| Tab | Address | What it holds |
|---|---|---|
| Profile | `/account` | name, handle, picture, meat proxy, public profile |
| Settings | `/account/settings` | preferences, the site's and the personal language, theme |
| Notifications | `/account/notifications` | mail, when mail goes out, agents that stop listening, browser notifications; a line leads to the language under Settings |
| Security | `/account/security` | its own tabs: Sign-in (second factor, then password), Sessions (`/sessions`), Another device (`/device`), Forge access (`/forge`), Your data (`/data`) |
| Organisations | `/account/orgs` | `js/orgs.js`, as before |
| Linked accounts | none | greyed, to come |

Security and Organisations are a human's alone, as in the menu before. On Sign-in the second
factor stands above the password form: the hub's mail and bell item about a changed or failed
second factor link to `/account/security` (`hub/src/maity_hub/notifications/mailer.py`,
`items.py`), and the hub stays unchanged on this card.

The addresses of the single page before the tabs are still reached from mails already sent, the
bell and the hub's links:
- `/account/picture`, `/account/preferences`, `/account/theme`, `/account/password`,
  `/account/sessions`, `/account/sign-in-device`, `/account/forge` and `/account/data` each lead
  to their tab. The new address replaces the old one in the history, the query goes along, and
  the heading of that part is focused.
- An unknown address leads to Profile, and an unknown tab of Security leads to Sign-in.
- `/settings/forge` is no old address: the contract names it as the setup's return (§16.11), so
  it shows Forge access itself (see the Forge access entry, 861705c6).

A change of view starts at the page's top (`js/app.js`, the route listener). Before, the
browser kept the scroll position of the page one came from. The board and an opened card count
as one view, so the card panel and the board's place on return stay as they were.

**Reason:** the account was a single page of eleven parts. One looked for a part by scrolling,
and the menu's entries were anchors into that page. Tabs show one part at a time, and each one
can be linked.

**Rejected alternatives:**
- Keeping the single page with the menu's anchors: this is what the card replaces.
- Letting the hub send the new addresses: the card leaves the hub unchanged, and mails already
  sent carry the old addresses anyway.
- Wrapping the tab rows: on a phone they would take two or three lines. The card asks for one
  row that scrolls, with the fade on the side that has more.
- Resetting the scroll on every change of address: opening a card on the board would jump to
  the top, and the board's place on return would be lost.
