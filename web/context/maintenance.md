# Maintenance

## The maintenance banner stands above the header, the full page is decided where a drawing starts

**Id:** 2d7a3955-c125-4911-8e23-72e996cb7631
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the web part of card tsk-12hwmpykz2ht (docs/api.md §16.12), 2026-11-02
**Revisit when:** the dashboard gets a layout that draws the whole page, header and banner included, in one place

The window of §16.12 is shown in two ways. The banner is one element
that `js/maintenance.js` puts above `#header`. A drawing replaces `#main`
and the header, but never the banner. The full page that stands in place
of the view while a window runs is decided in `render()` (`js/app.js`),
after `/auth/session` and `/me`, the two reads the hub still answers. The
sign-in page and the second-factor step are drawn as usual, so the
instance admin can sign in. The admin's own window section is the one
admin view drawn alone (`heldPage`).

**Reason:** §16.12 asks for the banner on every page, the public and
sign-in pages included. Those are drawn by several modules
(`js/visitor.js`, `js/invite.js`, the login in `js/app.js`), and each of
them clears `#main`. An element outside both containers survives every
drawing, with no change to any of those modules. Every other call is
refused during a window, so deciding once, before a view loads its data,
keeps the views from each having to handle the 503 themselves.

**Rejected alternatives:**
- The banner inside `#main`, inserted after each drawing as the sign-in
  banner is: every page module that draws on its own (visitor, invite,
  login) would have to call it, and a page that forgot would show none.
- Each view handling `503 maintenance` itself: dozens of places, and a
  view that loads in parallel reads would show half a page of errors.

## The window is learnt from three places, read at most once a minute

**Id:** d75409c4-2f1c-44ca-b892-c9b92542ebe3
**Type:** decision
**Status:** active
**Evidence:** inferred
**Source:** the web part of card tsk-12hwmpykz2ht (docs/api.md §16.12), 2026-11-02
**Revisit when:** the hub pushes the window over a stream the page already holds
**See:** maintenance.md#the-maintenance-banner-stands-above-the-header-the-full-page-is-decided-where-a-drawing-starts — 2d7a3955-c125-4911-8e23-72e996cb7631 — as of 2026-11-02

`js/maintenance.js` knows the window from `GET /maintenance` (at most
once a minute, before a drawing, for visitors too), from `/me`'s
`maintenance` (on every read of the counts), and from the details of any
`503 maintenance` (`js/api.js` hands every one to `M.onMaintenance`). Its
state is computed from `from` and `until` by the hub's clock as the page
knows it (`M.api.now`). One timer is set for the next boundary, so the
full page comes and goes without a request. While the full page stands,
it asks again every 30 seconds, so a window that is ended early or moved
shows at once. The fixture hub refuses like the hub does (the 503 before
the sign-in check, the same paths open), so fixture mode and the smoke
test see the full page as a browser would.

A page drawn for a running window marks itself (`aware`), and so does
the sign-in page. A refusal it still meets then redraws nothing. Without
that mark, a refused read on the sign-in page would redraw the page in
an endless loop: `/auth/methods` was refused by the hub until #1241
opened it on the lead's decision (tsk-12hwmpykz2ht), and a hub without
that change still refuses it.

**Reason:** a single source would miss cases. A visitor has no `/me`. A
window announced while a page is open reaches it through `/me` or the
first refusal. A start or end at a known time needs no read at all.

**Rejected alternative:** reading `GET /maintenance` on every drawing:
one more request per navigation for a state that changes a few times a
year.
