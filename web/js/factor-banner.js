// Toward an authenticator app (docs/api.md §2.10, tsk-yksxdpd2pk0m): a human whose second
// factor is the mail (`via: email` in GET /auth/second-factor) sees a banner on every page,
// linking to Security. Its sentence says whether a reset by mail could reach them: the
// instance offers it (`password_reset` in GET /auth/methods) and their own switch is on
// (`email.password_reset`). "Later" hides it until the next sign-in; enrolling TOTP ends it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;
  // The session "Later" was chosen in; a new sign-in is a new session, and the banner is back.
  const LATER = "maity.factor-banner.later";

  // What the banner stands on, kept for a minute at most: three reads on each page would be
  // three calls on every click. Read again before that after a write of this tab that may
  // change it (a switch turned off, TOTP enrolled), on Security, where the human looks at the
  // factor, and when the tab is shown again: another tab, another device or an admin may have
  // changed it meanwhile, and a banner that says the mailbox alone signs in must not outlive
  // an app enrolled elsewhere (#1716 review).
  const MAX_AGE_MS = 60000;
  let reading = null;
  let readAt = 0;
  let laterHere = null; // where the browser keeps nothing, "Later" holds for this page load

  function forget() { reading = null; }
  if (window.document && window.document.addEventListener) {
    window.document.addEventListener("visibilitychange", () => { if (window.document.visibilityState === "visible") forget(); });
  }
  // A write that may change it: the human's mail settings (their switch), the second factor
  // (TOTP enrolled ends the banner), the instance's sign-in settings (the reset offered).
  const MOVES = /^\/(?:me\/notification-settings|auth\/second-factor|admin\/settings\/sign-in)(?:[/?]|$)/;
  function wrote(path) { if (typeof path === "string" && MOVES.test(path)) forget(); }

  function read() {
    if (reading && M.api.now() - readAt >= MAX_AGE_MS) forget();
    if (!reading) {
      readAt = M.api.now();
      reading = (async () => {
        const factor = await M.api.get("/auth/second-factor");
        if (!factor || factor.via !== "email") return null;
        // Either read failing says nothing of the reset: the milder sentence, never a claim.
        const [methods, settings] = await Promise.all([
          M.api.get("/auth/methods").catch(() => null),
          M.api.get("/me/notification-settings").catch(() => null),
        ]);
        const reset = !!(methods && methods.password_reset && settings && settings.email && settings.email.password_reset !== false);
        return { reset };
      })();
      reading.catch(() => { reading = null; });
    }
    return reading;
  }

  function laterFor() {
    try { return window.localStorage.getItem(LATER); } catch (err) { return laterHere; }
  }

  function setLater(sessionId) {
    laterHere = sessionId;
    try { window.localStorage.setItem(LATER, sessionId); } catch (err) { /* this browser keeps nothing */ }
  }

  // The banner for this session, or null. sessionId: GET /auth/session's `session_id`;
  // fresh: read again whatever is kept (Security).
  async function banner(sessionId, fresh, onHide) {
    if (sessionId && laterFor() === sessionId) return null;
    if (fresh) forget();
    let state;
    try {
      state = await read();
    } catch (err) {
      return null;
    }
    if (!state) return null;
    const link = h("a", { href: "/account/security" }, M.t("factor_banner.link"));
    const box = h("div", { class: "factor-banner", role: "region", "aria-label": M.t("factor_banner.label") });
    append(box, h("div", { class: "flag" },
      h("p", null, state.reset ? M.tn("factor_banner.mailbox_alone", { link }) : M.tn("factor_banner.mailbox", { link })),
      h("button", { type: "button", class: "small", onclick: () => { if (sessionId) setLater(sessionId); box.remove(); if (onHide) onHide(); } }, M.t("factor_banner.later"))));
    return box;
  }

  M.factorBanner = { banner, forget, wrote };
})(window.Maity);
