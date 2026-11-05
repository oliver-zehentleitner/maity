# Mail sign-in

## A link and its browser-bound code spend one grant; guesses are serialised per human

**Id:** 24bacf7b-862a-4c2a-b702-a851c8cb386d
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** docs/api.md §2.6.3–§2.6.5 and the mail sign-in implementation, 2026-10-25
**Revisit when:** issuance, code redemption or link completion can run without the human row lock

The link's nonce hash and the requesting browser's pending-cookie hash name the
same `email_sign_in` row. A conditional update of its unused, unexpired state is
the final check before creating a session. Code guesses additionally lock the
human row and reread the flow, so a request that read before the fifth wrong
guess cannot use the stale proof afterwards. The per-human UTC-day wrong-code
counter uses that same lock, across every source address and every flow.

**Reason:** separate used markers for the link and code would need to be changed
atomically everywhere; one grant gives both paths the same last check. A lock on
one flow alone cannot enforce the twenty-guess limit across several flows. The
human row already exists before a flow or a daily counter does, so it also
serialises creating those rows without an insert race on the server engines.
SQLite takes its equivalent write lock at transaction start.

Five wrong guesses remove only that code's proof; twenty remove every code proof
of the human and suppress new codes until the UTC day changes. They do not spend
the grant: the unguessable signed link stays usable. The route must commit wrong
guesses before returning `code_invalid`, since raising inside the transaction
would roll back the budget.

**Rejected alternatives:** separate link/code used flags, or a counter per flow
alone: they leave a second redemption path or let distributed guesses multiply
the human's allowed guesses. The limits and continued validity of the links are
contract requirements, not new policy introduced by this implementation.

## Mail sign-in becomes available only with its complete first-factor path

**Id:** 36284c53-8139-4c41-99c0-9123e9e2c4f2
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** docs/api.md §2.6 and §2.8; coordinator review of the predecessor entry, 2026-10-28
**Revisit when:** mail sign-in should be offered with only part of its path, or the conditions for advertising it in §2.6 change

The instance advertises mail sign-in only when the method, SMTP and signing
key are available. Both redemption paths use the same second-factor entry
point as password login; owning the mailbox proves only the first factor.
The earlier `not_implemented` guard is removed with the routes, grant state,
mail delivery and invalidation hooks in this change.

**Reason:** the old guard prevented advertising an unavailable method. Once
that path exists, keeping the guard would hide a working method; issuing a
full session directly would instead bypass an enrolled human's second factor.

**Rejected alternatives:** retaining the placeholder after implementation, or
creating sessions directly from a valid mailed proof instead of entering the
existing second-factor flow.

## The sign-in link page and its dead-link page stand in the frame of the pages without a session, with no product line

**Id:** 89e8318d-c18e-46a6-8617-97f0c600ade0
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** card tsk-qez5k81hnkjc (the maintainer found the page bare, 2026-11-03) and lotse#wtwy's answers on it (2026-11-04): the frame's footer instead of the product line, as on the framed `/login` (req-5k1gvfsmcg9k); `render.door_document`, `routes/email_sign_in.py`. The policy's shape is this entry's reading of the legal pages' entry (landing.md, dde46a41)
**Revisit when:** the page needs a script, the dashboard takes the link over, the dashboard's `/login` gets the product line back, anything a user stores can be answered under the public host's origin as a stylesheet or a font, or `public-pages.css` stops colouring the header's mark

`GET /mail/sign-in/{token}` and every dead link of it (`404`, never which reason) are drawn by
`render.door_document`: the landing page's header and footer from the frame's model (§16.7.5),
and between them the door of `public-pages.css`, the dark panel with its art and the form's column,
as the dashboard draws `/login`. The link page is in the person's text language; the dead-link
page, where nobody is known, in the browser's (`Accept-Language` among §16.7's languages, else
English). The frame's model is chosen with the page's language first; where the landing page does
not have it, header and footer carry their own `lang`. The footer has no language switch: the
page's language is the person's, and a `?lang=` on the address would change nothing. The
behaviour is as before: the `GET` changes nothing but the form cookie, one explicit button posts.

The answers carry `default-src 'none'; style-src 'self' '<hash of the fallback style>';
font-src 'self'; img-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'`
and `Referrer-Policy: no-referrer`. There is no script and no `'unsafe-inline'`. The header's
mark is inlined without its `style` attributes, which the landing and legal pages allow with
`'unsafe-inline'` (landing.md, 7c22ec9b and dde46a41); `public-pages.css` colours it, as on
the dashboard's framed pages (`web/js/site-chrome.js`). So the only inline style is the legal pages' old
`STYLE`, drawn when the landing stylesheets are missing, and the policy allows exactly that
block by its hash; a browser logs no violation.

**Reason:** the page is the step after the mail on the way into `/login`'s design, so it should
look like the pages around it. The landing page's files carry no risk for a page with a token in
its address, for the reasons the legal pages' entry gives: they are first-party, served under their
digest, `nosniff`, never from the database. Nothing is loaded from elsewhere, and no referrer
leaves the page. `form-action 'self'` is new: the old policy did not restrict where the form posts.

**Rejected alternatives:**
- The registration link page's shell (`render.form_document`, mail.md f63430e9): it looks like the
  old legal pages, not like `/login`, which the card asked for.
- The product line under the frame's footer, as the card first said: superseded by lotse#wtwy,
  so that every page without a session ends the same way as the framed `/login`.
- `'unsafe-inline'` for the fallback, as the legal pages have: it would allow every inline style on
  a page with a token in its address, where a hash allows the one block the hub writes.

## The pages of §18.6 share the sign-in link page's frame and policy through one helper

**Id:** 78d58e3b-259a-4530-a970-c907027e5f7c
**Type:** decision
**Status:** active
**Evidence:** confirmed
**Source:** card tsk-w62n5p0v9d47 and lotse#wtwy's go on its plan (2026-11-05); contract `docs/api.md` §16.7.5, §18.6 (#1394); `link_frame.py`, `routes/mail_links.py`; why the policy changed is the root's context/security.md, 8191d964

The four pages of `routes/mail_links.py` and the sign-in link's page are drawn by one helper,
`link_frame.page`, which reads the frame's model and answers with `link_frame.HEADERS`
(`render.DOOR_CSP`, `Referrer-Policy: no-referrer`). The four pages of `mail_links.py` keep their
words, statuses, the GET that changes nothing and the one button, and their content stands in a
`.link-page` block of the door's column, which `public-pages.css` gives paragraph spacing and the
quote's rule. The sign-in link's page keeps its own content and its GET's form cookie, as above. A test
pins the policy string and fetches each stylesheet the page names with the test client: served
200 as `text/css` with `nosniff`, and every `url(...)` in it relative, the hub's own (no browser
applies the policy there).

**Reason:** one helper keeps the five link pages under one policy and one frame, so a change to
either reaches all of them. The `.link-page` scope keeps the new rules off the dashboard's own
door pages, which share the stylesheet.

**Rejected alternatives:**
- A second copy of the sign-in page's `_page` in `mail_links.py`: two places to keep alike.
- Unscoped `.door-form p` rules: they would reach the dashboard's sign-in paragraphs as well.
