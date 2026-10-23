// Sessions (docs/api.md §2.6.5, §2.6.7; #/account/sessions): where the
// human is signed in, with "This was me" for a sign-in alert, End per
// session and End all other sessions, the ended ones of the last 30 days,
// and a held address change (§2.6.3) to approve or reject. What this
// session may do follows the hub's rules, said before it is tried: one not
// in good standing ends no session in good standing, and while under an
// hour old no older one. The banner of a mail sign-in shows in every other
// session, on every page, while its alert is unread and the session it
// reports, or one that session approved, is still active.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;

  const HOUR = 3600 * 1000;
  const METHOD_WORDS = { password: "password", device_code: "a code from another device", email_link: "a link by mail", email_code: "a code by mail" };
  const ENDED_WORDS = { logout: "signed out", revoked: "ended", end_others: "ended with the others", expired: "expired", password_change: "ended by a password change" };
  const MAIL = ["email_link", "email_code"];
  // Unread security items are few (the mail limits); read at most this many pages.
  const ALERT_PAGES = 10;
  // A hub that answered 404 to the session list has none: not asked again
  // until the page is loaded anew.
  let hubWithout = false;

  // The hub's refusals, in words (§2.6.5, §2.6.3).
  function said(err) {
    const why = err.details && err.details.reason;
    if (why === "not_in_good_standing") return { message: "this session's own sign-in is not confirmed yet; confirm it from another session first" };
    if (why === "session_too_new") return { message: "this session is too new for that" };
    if (err.code === "conflict") return { message: "it was replaced by a newer change, shown now" };
    return err;
  }

  // Every unread security item, following the cursor.
  async function unreadAlerts() {
    const items = [];
    let cursor = null;
    for (let n = 0; n < ALERT_PAGES; n++) {
      const page = await M.api.get("/me/notifications?kind=security&unread=true&limit=50" + (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""));
      items.push(...(page.items || []));
      cursor = page.next_cursor;
      if (!cursor) break;
    }
    return items;
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
      alerts = await unreadAlerts();
    } catch (err) {
      if (err.status !== 404) throw err;
    }
    return { sessions, alerts, current: sessions.find((s) => s.current) || null };
  }

  // Times as instants, on the hub's clock (M.api.now carries its offset).
  const at = (iso) => Date.parse(iso);
  const young = (s, hours) => M.api.now() - at(s.created_at) < hours * HOUR;
  const device = (s) => (s.browser || "A browser") + " on " + (s.os || "an unknown system");
  // "This was me" (§18.3): from a session in good standing that existed
  // before what the alert reports, never from the reported session itself.
  // An alert with no session (an address change) is judged by its time;
  // the hub also refuses the session that made the change, which the page
  // cannot see, so the answer is checked afterwards.
  function mayConfirm(cur, alert, reported) {
    if (!cur || !cur.good_standing) return false;
    if (reported) return reported.id !== cur.id && at(cur.created_at) < at(reported.created_at);
    return at(cur.created_at) < at(alert.at);
  }
  // Why End is not offered for a session, or null when it is (§2.6.5).
  function cannotEnd(cur, s) {
    if (!cur || s.current || cur.good_standing) return null;
    if (s.good_standing) return "Confirm this session's sign-in from another session first.";
    if (young(cur, 1) && at(s.created_at) < at(cur.created_at)) return "This session is too new to end older ones.";
    return null;
  }
  // The sessions a session approved by device code, and theirs in turn.
  function approvedBy(sessions, s) {
    const direct = sessions.filter((x) => x.approved_by === s.id);
    return direct.concat(...direct.map((x) => approvedBy(sessions, x)));
  }
  // What keeps a mail sign-in's banner up: the session, or one it approved, still active.
  const liveOf = (sessions, s) => [s].concat(approvedBy(sessions, s)).filter((x) => !x.ended_at);

  async function confirm(alert) {
    await M.api.post("/me/notifications/read", { ids: [alert.id] });
  }
  async function end(s) {
    await M.api.del("/auth/sessions/" + encodeURIComponent(s.id));
  }
  // The hub answers 200 even when it skipped the id (§18.3): confirmed only
  // when the alert is no longer unread.
  const confirmedWords = (alert, words) => (data) => (data && data.alerts.some((a) => a.id === alert.id)
    ? "The hub did not confirm it from this session." : words);

  // The account's section; it redraws in place after each change.
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
    // done is the words, or a function of what was read afterwards.
    async function act(busy, fn, done) {
      status.busy(busy);
      try {
        await fn();
      } catch (err) {
        // A change replaced meanwhile: the one that replaced it is shown.
        if (err.code === "conflict") await draw();
        status.fail("Not done: ", said(err));
        status.el.focus();
        return;
      }
      const data = await draw();
      status.done();
      append(status.el, h("span", { class: "ok" }, typeof done === "function" ? done(data) : done));
      status.el.focus();
    }

    // "This was me" for an alert, where this session may mark it.
    const confirmButton = (cur, alert, reported, label) => (alert && mayConfirm(cur, alert, reported)
      ? h("button", { type: "button", class: "small", "aria-label": "This was me: " + label,
        onclick: () => act("Confirming…", () => confirm(alert), confirmedWords(alert, "Confirmed: " + label + " is yours.")) }, "This was me")
      : null);

    async function draw() {
      let data;
      try {
        data = await load();
      } catch (err) {
        append(clear(body), h("p", { class: "send-status failed" }, err.status === 404 ? "This hub lists no sessions yet." : "Could not read your sessions: " + err.message));
        return null;
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
            confirmButton(cur, alert, s, device(s)),
            h("button", { type: "button", class: "small", disabled: why ? true : null, "aria-describedby": why ? "why-" + s.id : null,
              "aria-label": "End the session " + device(s),
              onclick: () => act("Ending…", () => end(s), "Ended " + device(s) + ".") }, "End"),
            why ? h("p", { class: "hint", id: "why-" + s.id }, why) : null));
      };
      // An ended session whose sign-in alert is still unread keeps its This was me.
      const endedRow = (s) => {
        const alert = alertOf(s);
        return h("li", { class: "muted", "data-session": s.id },
          device(s) + ", " + (ENDED_WORDS[s.ended_by] || s.ended_by) + " " + formatTime(s.ended_at) + ".",
          alert ? [" Its sign-in alert is not confirmed. ", confirmButton(cur, alert, s, device(s))] : null);
      };
      // Alerts with no session in the list (an address change, §2.6.3).
      const loose = alerts.filter((a) => !(a.target && a.target.type === "session" && sessions.some((s) => s.id === a.target.id)));
      const endedOpen = ended.some(alertOf);
      append(clear(body),
        h("ul", { class: "session-list" }, active.map(row)),
        others.length ? h("div", { class: "actions" },
          h("button", { type: "button", disabled: othersBlocked ? true : null, "aria-describedby": othersBlocked ? "why-end-others" : null,
            onclick: () => act("Ending…", () => M.api.post("/auth/sessions/end-others", {}), "Every other session was ended"
              + (cur && !cur.good_standing ? " that is not confirmed." : ".")) }, "End all other sessions"),
          othersBlocked ? h("p", { class: "hint", id: "why-end-others" }, "This session is too new to end older ones.")
            : cur && !cur.good_standing ? h("p", { class: "hint" }, "From here this ends only the other sessions that are not confirmed.") : null) : null,
        loose.length ? [h("h4", null, "Other alerts"), h("ul", { class: "session-alerts" }, loose.map((a) => h("li", { "data-alert": a.id },
          a.title, h("span", { class: "muted" }, " · " + formatTime(a.at)), " ", confirmButton(cur, a, null, a.title))))] : null,
        ended.length ? h("details", { class: "sessions-ended", open: endedOpen ? true : null },
          h("summary", null, "Ended in the last 30 days (" + ended.length + ")"),
          h("ul", null, ended.map(endedRow))) : null,
        await addressChange(ctx, cur, sessions, act));
      return data;
    }
    await draw();
    return { el: box, heading };
  }

  // A held address change (§2.6.3): approve needs good standing and a
  // session at least a day old, reject good standing; both name the change.
  // Which session asked is said: the 24-hour rule exists for a change filed
  // from a session that is not confirmed.
  async function addressChange(ctx, cur, sessions, act) {
    let settings;
    try {
      settings = M.notify && M.notify.state.available === false ? null : await M.api.get("/me/notification-settings");
    } catch (err) {
      return null;
    }
    const held = settings && settings.email && settings.email.address_change;
    if (!held) return null;
    const names = { id: held.id, address: held.address };
    const from = sessions.find((s) => s.id === held.session_id);
    const why = !cur || !cur.good_standing ? "Only a confirmed session can decide it."
      : young(cur, 24) ? "Approving needs a session at least a day old; this one can reject it." : null;
    return h("div", { class: "address-change", role: "group", "aria-labelledby": "address-change-title" },
      h("h4", { id: "address-change-title" }, "An address change waits for you"),
      h("p", null, held.address === null ? "Remove the sign-in address" : "Change the sign-in address to " + held.address,
        h("span", { class: "muted" }, ", asked " + formatTime(held.requested_at)
          + (from ? " from " + device(from) + ", " + (from.created ? from.created.ip : from.ip) + ", " + (from.good_standing ? "confirmed" : "not confirmed") : "") + ".")),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "small", disabled: why ? true : null,
          onclick: () => act("Approving…", () => M.api.post("/me/notification-settings/email/address-change/approve", names), "Approved.") }, "Approve"),
        h("button", { type: "button", class: "small", disabled: !cur || !cur.good_standing ? true : null,
          onclick: () => act("Rejecting…", () => M.api.post("/me/notification-settings/email/address-change/reject", names), "Rejected.") }, "Reject")),
      why ? h("p", { class: "hint" }, why) : null);
  }

  // The mail sign-in banner (§2.6.5): in every other session, while the
  // alert is unread and the session it reports, or one it approved, is
  // still active. End this session ends those that are, asking nothing
  // more, and follows the same rules as the list; This was me only where
  // allowed.
  async function banner(ctx, onChange) {
    let data;
    try {
      data = await load();
    } catch (err) {
      return null;
    }
    const { sessions, alerts, current: cur } = data;
    const shown = alerts.map((a) => {
      const s = a.target && a.target.type === "session" && sessions.find((x) => x.id === a.target.id);
      return { a, s, live: s ? liveOf(sessions, s).filter((x) => !x.current) : [] };
    }).filter(({ s, live }) => s && !s.current && MAIL.includes(s.method) && live.length);
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
    shown.forEach(({ a, s, live }, i) => {
      const why = live.map((x) => cannotEnd(cur, x)).find(Boolean) || null;
      const through = live.filter((x) => x.id !== s.id);
      append(box, h("div", { class: "flag" },
        h("p", null, "New sign-in by mail: " + device(s) + ", " + (s.created ? s.created.ip : s.ip) + ", " + formatTime(s.created_at) + "."
          + (s.ended_at ? " It has ended, but a session it approved is still active: " + through.map(device).join(", ") + "."
            : through.length ? " It approved: " + through.map(device).join(", ") + "." : "")),
        h("button", { type: "button", class: "small", disabled: why ? true : null, "aria-describedby": why ? "banner-why-" + i : null,
          onclick: () => run(async () => { for (const x of live) await end(x); }) }, "End this session"), " ",
        mayConfirm(cur, a, s) ? h("button", { type: "button", class: "small", onclick: () => run(() => confirm(a)) }, "This was me") : null,
        why ? h("p", { class: "hint", id: "banner-why-" + i }, why) : null));
    });
    append(box, status.el);
    return box;
  }

  M.sessions = { section, banner, said };
})(window.Maity);
