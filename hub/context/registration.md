# Registration

The registration's link page (`routes/register_page.py`, docs/api.md §2.7.1) beyond its frame and form: what it offers when the link cannot make the account, and how the handle's rule is said there. The page's router, cookies and frame are in [mail.md](mail.md).

## The registration's link page offers "Register again" and hands the address over in a cookie; the handle's rule is checked by the field and the stylesheet

**Id:** 0c6183d9-2214-4d16-a10c-a28f8ab1c0c5
**Type:** decision
**Type:** constraint
**Status:** active
**Evidence:** inferred
**Source:** card tsk-pxc5cx4hgb0y (an owner request, 2026-11-14: a new user mistyped the password at sign-up and the page offered no way on), and the lead's go to change the hub's page for it; `routes/register_page.py` `_again`, `_set_again_cookie`, `HANDLE_PATTERN`; `public-pages.css`; `web/js/register.js`. The choice of the cookie and of the stylesheet is this entry's reading of the card's limits (no address in clear text in the address where avoidable, no API change)
**Revisit when:** the page gets a script, the sign-up page can be given the address another way (a pending registration it can read, a form the hub serves itself), or `/register` moves
**See:** mail.md#the-registrations-link-page-stands-in-the-frame-of-the-pages-without-a-session-like-the-sign-in-links-page — e3267520-bfef-40e3-aa6f-17cecd17147c — as of 2026-11-14

A wrong password's answer, and the dead link's page, offer **Register again**: a link to
`/register` (the frame adds `?lang=`; the stored `next` goes along where it is not `/`, so an
invitation's sign-up stays one) and one sentence, that the newest mail's link replaces the earlier
one, which is how §2.7.1 already works. Under the refused password it is a link, since typing the
password again is the other way on; on the dead page, the only way on, a button. After a wrong
password the answer also sets `maity_register_again`: the address percent-encoded, `Path=/register`,
`SameSite=Strict`, ten minutes, not `HttpOnly`, so the sign-up page's script fills the field and
removes it. The dead page sets none and names no address: it never says whose link it was or why it
died.

The handle field carries the hub's syntax as its `pattern` (equal to `models.HANDLE_PATTERN`, a
test holds them alike), the rule beside it, and a word ("lowercase only…") that `public-pages.css`
shows for `#handle:not(:placeholder-shown):invalid`; the placeholder is one space, so an empty field
says nothing. The browser's own check stops a broken handle before it is sent. A handle refused by
the hub for an upper-case letter gets that same word. Nothing is lower-cased for the person.

**Reason:** the address is shown on the page already, to whoever holds the link, so handing it to
the next page tells nobody anything new; a cookie only `/register` is sent keeps it out of the
browser's history, a copied link and the request log, where `?address=` would put it. The page's
policy has no script (email-links.md, 89e8318d), so a check while typing has to come from the field
and the stylesheet; the stylesheet cannot tell an upper-case letter from another break of the rule,
so the word names the upper-case case first and the rule stands beside it.

**Rejected alternatives:**
- The address in the sign-up page's query or fragment: in the address in clear text, which the card
  asked to avoid where the page can carry it another way.
- An API read of the pending registration's address by token for `/register`: a new route, which the
  card ruled out.
- A hashed inline script for this page to check the handle as `web/js/handles.js` does: it would
  give the one page with a token in its address a script, against the door's policy, for a hint the
  stylesheet can show.
- `novalidate` with the stylesheet's word only: the person would still send a handle the hub refuses
  with one more round.
