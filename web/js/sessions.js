// Sessions (docs/api.md §2.6.5, §2.6.7; #/account/sessions): where the
// human is signed in, with "This was me" for a sign-in alert, End per
// session and End all other sessions, the ended ones of the last 30 days,
// and a held address change (§2.6.3) to approve or reject. What this
// session may do follows the hub's rules, said before it is tried: one not
// in good standing ends no session in good standing, and while under an
// hour old no older one. The banner of a mail sign-in shows in every other
// session, on every page, while its alert is unread.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  const HOUR = 3600 * 1000;
  const METHOD_WORDS = { password: "password", device_code: "a code from another device", email_link: "a link by mail", email_code: "a code by mail" };
  const ENDED_WORDS = { logout: "signed out", revoked: "ended", end_others: "ended with the others", expired: "expired", password_change: "ended by a password change" };
  const MAIL = ["email_link", "email_code"];
  // A hub that answered 404 to the session list has none: not asked again
  // until the page is loaded anew.
  let hubWithout = false;

  // The hub's refusals, in words (§2.6.5, §2.6.3).
  function said(err) {
    const why = err.details && err.details.reason;
    if (why === "not_in_good_standing") return { message: "this session's own sign-in is not confirmed yet; confirm it from another session first" };
    if (why === "session_too_new") return { message: "this session is too new for that" };
    if (err.code === "conflict") return { message: "it was replaced by a newer change; read it again" };
    return err;
  }

  // What the hub has: the sessions (ended ones too) and the unread security
  // items; a hub without notifications has no items, not an error.
  async function load() {
    if (hubWithout) throw new M.api.ApiError("no sessions", 404, "/auth/sessions", "not_found");
    let sessions;
    try {
      sessions = (await M.api.get("/auth/sessions?ended=true")).items;
    } catch (err) {
      if (err.status === 404) hubWithout = true;
      throw err;
    }
    let alerts = [];
    try {
      alerts = (await M.api.get("/me/notifications?kind=security&unread=true&limit=50")).items || [];
    } catch (err) {
      if (err.status !== 404) throw err;
    }
    return { sessions, alerts, current: sessions.find((s) => s.current) || null };
  }

  const young = (s, hours) => Date.now() - Date.parse(s.created_at) < hours * HOUR;
  const device = (s) => (s.browser || "A browser") + " on " + (s.os || "an unknown system");
  // "This was me" (§18.3): from a session in good standing that existed
  // before what the alert reports, never from the reported session itself.
  function mayConfirm(cur, alert, reported) {
    if (!cur || !cur.good_standing) return false;
    if (reported) return reported.id !== cur.id && cur.created_at < reported.created_at;
    return cur.created_at < alert.at;
  }
  // Why End is not offered for a session, or null when it is (§2.6.5).
  function cannotEnd(cur, s) {
    if (!cur || s.current || cur.good_standing) return null;
    if (s.good_standing) return "Confirm this session's sign-in from another session first.";
    if (young(cur, 1) && s.created_at < cur.created_at) return "This session is too new to end older ones.";
    return null;
  }

  async function confirm(alert) {
    await M.api.post("/me/notifications/read", { ids: [alert.id] });
  }
  async function end(s) {
    await M.api.del("/auth/sessions/" + encodeURIComponent(s.id));
  }

  // The account's section; again() redraws it in place after each change.
  async function section(ctx) {
    const heading = h("h3", { id: "sessions-heading", class: "sessions-heading", tabindex: "-1" }, "Sessions");
    const box = h("section", { class: "sessions", "aria-labelledby": "sessions-heading" });
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const body = h("div");
    append(box, heading,
      h("p", { class: "muted" }, "Where you are signed in. Browser and system are what each device said about itself; the address is what the hub saw."),
      body, status.el);

    // A change, then the list again; the status line says what happened.
    async function act(busy, fn, done) {
      status.busy(busy);
      try {
        await fn();
      } catch (err) {
        status.fail("Not done: ", said(err));
        status.el.focus();
        return;
      }
      await draw();
      status.done();
      append(status.el, h("span", { class: "ok" }, done));
      status.el.focus();
    }

    async function draw() {
      let data;
      try {
        data = await load();
      } catch (err) {
        append(clear(body), h("p", { class: "send-status failed" }, err.status === 404 ? "This hub lists no sessions yet." : "Could not read your sessions: " + err.message));
        return;
      }
      const { sessions, alerts, current: cur } = data;
      const active = sessions.filter((s) => !s.ended_at);
      const ended = sessions.filter((s) => s.ended_at);
      const alertOf = (s) => alerts.find((a) => a.target && a.target.type === "session" && a.target.id === s.id);
      const others = active.filter((s) => !s.current);
      const othersBlocked = cur && !cur.good_standing && young(cur, 1);
      const row = (s) => {
        const alert = alertOf(s);
        const why = cannotEnd(cur, s);
        return h("li", { class: "session" + (s.current ? " current" : ""), "data-session": s.id },
          h("div", { class: "session-head" },
            h("strong", null, device(s)), s.current ? h("span", { class: "badge" }, "this browser") : null,
            h("span", { class: s.good_standing ? "badge ok" : "badge warn" }, s.good_standing ? "confirmed" : "not confirmed")),
          h("p", { class: "muted" }, "Signed in with " + (METHOD_WORDS[s.method] || s.method) + ", " + formatTime(s.created_at)
            + " from " + (s.created ? s.created.ip : s.ip) + "; last seen " + formatAgo(s.last_seen_at) + " from " + s.ip
            + (s.approved_by ? "; approved from " + device(sessions.find((x) => x.id === s.approved_by) || {}) : "") + "."),
          alert ? h("p", { class: "flag" }, "Its sign-in alert is not confirmed.") : null,
          s.current ? null : h("div", { class: "actions" },
            alert && mayConfirm(cur, alert, s) ? h("button", { type: "button", class: "small", "aria-label": "This was me: " + device(s),
              onclick: () => act("Confirming…", () => confirm(alert), "Confirmed: " + device(s) + " is yours.") }, "This was me") : null,
            h("button", { type: "button", class: "small", disabled: why ? true : null, "aria-describedby": why ? "why-" + s.id : null,
              "aria-label": "End the session " + device(s),
              onclick: () => act("Ending…", () => end(s), "Ended " + device(s) + ".") }, "End"),
            why ? h("p", { class: "hint", id: "why-" + s.id }, why) : null));
      };
      // Alerts with no session in the list (an address change, §2.6.3).
      const loose = alerts.filter((a) => !(a.target && a.target.type === "session" && sessions.some((s) => s.id === a.target.id)));
      append(clear(body),
        h("ul", { class: "session-list" }, active.map(row)),
        others.length ? h("div", { class: "actions" },
          h("button", { type: "button", disabled: othersBlocked ? true : null, "aria-describedby": othersBlocked ? "why-end-others" : null,
            onclick: () => act("Ending…", () => M.api.post("/auth/sessions/end-others", {}), "Every other session was ended"
              + (cur && !cur.good_standing ? " that is not confirmed." : ".")) }, "End all other sessions"),
          othersBlocked ? h("p", { class: "hint", id: "why-end-others" }, "This session is too new to end older ones.")
            : cur && !cur.good_standing ? h("p", { class: "hint" }, "From here this ends only the other sessions that are not confirmed.") : null) : null,
        loose.length ? [h("h4", null, "Other alerts"), h("ul", { class: "session-alerts" }, loose.map((a) => h("li", null,
          a.title, h("span", { class: "muted" }, " · " + formatTime(a.at)), " ",
          mayConfirm(cur, a, null) ? h("button", { type: "button", class: "small", "aria-label": "This was me: " + a.title,
            onclick: () => act("Confirming…", () => confirm(a), "Confirmed.") }, "This was me") : null)))] : null,
        ended.length ? h("details", { class: "sessions-ended" }, h("summary", null, "Ended in the last 30 days (" + ended.length + ")"),
          h("ul", null, ended.map((s) => h("li", { class: "muted" }, device(s) + ", " + (ENDED_WORDS[s.ended_by] || s.ended_by) + " " + formatTime(s.ended_at) + ".")))) : null,
        await addressChange(ctx, cur, act));
    }
    await draw();
    return { el: box, heading };
  }

  // A held address change (§2.6.3): approve needs good standing and a
  // session at least a day old, reject good standing; both name the change.
  async function addressChange(ctx, cur, act) {
    let settings;
    try {
      settings = M.notify && M.notify.state.available === false ? null : await M.api.get("/me/notification-settings");
    } catch (err) {
      return null;
    }
    const held = settings && settings.email && settings.email.address_change;
    if (!held) return null;
    const names = { id: held.id, address: held.address };
    const why = !cur || !cur.good_standing ? "Only a confirmed session can decide it."
      : young(cur, 24) ? "Approving needs a session at least a day old; this one can reject it." : null;
    return h("div", { class: "address-change", role: "group", "aria-labelledby": "address-change-title" },
      h("h4", { id: "address-change-title" }, "An address change waits for you"),
      h("p", null, held.address === null ? "Remove the sign-in address" : "Change the sign-in address to " + held.address,
        h("span", { class: "muted" }, ", asked " + formatTime(held.requested_at) + ".")),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "small", disabled: why ? true : null,
          onclick: () => act("Approving…", () => M.api.post("/me/notification-settings/email/address-change/approve", names), "Approved.") }, "Approve"),
        h("button", { type: "button", class: "small", disabled: !cur || !cur.good_standing ? true : null,
          onclick: () => act("Rejecting…", () => M.api.post("/me/notification-settings/email/address-change/reject", names), "Rejected.") }, "Reject")),
      why ? h("p", { class: "hint" }, why) : null);
  }

  // The mail sign-in banner (§2.6.5): in every other session, while the
  // alert is unread and the session it reports is still active. End this
  // session asks nothing more; This was me only where allowed.
  async function banner(ctx, onChange) {
    let data;
    try {
      data = await load();
    } catch (err) {
      return null;
    }
    const { sessions, alerts, current: cur } = data;
    const shown = alerts.map((a) => ({ a, s: a.target && a.target.type === "session" && sessions.find((x) => x.id === a.target.id) }))
      .filter(({ s }) => s && !s.ended_at && !s.current && MAIL.includes(s.method));
    if (!shown.length) return null;
    const box = h("div", { class: "signin-banner", role: "region", "aria-label": "New sign-ins by mail" });
    const status = M.statusLine();
    const run = async (fn) => {
      status.busy("…");
      try {
        await fn();
      } catch (err) {
        status.fail("Not done: ", said(err));
        return;
      }
      onChange();
    };
    shown.forEach(({ a, s }) => append(box, h("p", { class: "flag" },
      "New sign-in by mail: " + device(s) + ", " + (s.created ? s.created.ip : s.ip) + ", " + formatTime(s.created_at) + ". ",
      h("button", { type: "button", class: "small", onclick: () => run(() => end(s)) }, "End this session"), " ",
      mayConfirm(cur, a, s) ? h("button", { type: "button", class: "small", onclick: () => run(() => confirm(a)) }, "This was me") : null)));
    append(box, status.el);
    return box;
  }

  M.sessions = { section, banner, said };
})(window.Maity);
