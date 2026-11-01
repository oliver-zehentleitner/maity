// Sessions (docs/api.md §2.6.5, §2.6.7; /account/sessions): where the
// human is signed in, with "This was me" for a sign-in alert, End per
// session and End all other sessions, which passed the second factor (§2.8.7),
// the ended ones of the last 30 days,
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
  const OK_BADGE = "badge ok";
  // How a session signed in, and how it ended, in words from the catalog when drawn.
  const METHOD_WORDS = {
    password: () => M.t("sessions.method.password"), device_code: () => M.t("sessions.method.device_code"),
    email_link: () => M.t("sessions.method.email_link"), email_code: () => M.t("sessions.method.email_code"),
  };
  const ENDED_LINES = {
    logout: (o) => M.t("sessions.ended.logout", o), revoked: (o) => M.t("sessions.ended.revoked", o),
    end_others: (o) => M.t("sessions.ended.end_others", o), expired: (o) => M.t("sessions.ended.expired", o),
    password_change: (o) => M.t("sessions.ended.password_change", o),
    second_factor_reset: (o) => M.t("sessions.ended.second_factor_reset", o),
  };
  const methodOf = (s) => (Object.hasOwn(METHOD_WORDS, s.method) ? METHOD_WORDS[s.method]() : s.method);
  // A session's line: how and when it signed in, last seen, and who approved it, as one sentence.
  function lineOf(s, sessions) {
    const o = { method: methodOf(s), when: formatTime(s.created_at), from: s.created ? s.created.ip : s.ip, ago: formatAgo(s.last_seen_at), ip: s.ip };
    if (!s.approved_by) return M.t("sessions.line", o);
    return M.t("sessions.line.approved", Object.assign(o, { approver: device(sessions.find((x) => x.id === s.approved_by) || {}) }));
  }
  // When and from which session an address change was asked, as one sentence.
  function askedFrom(held, from) {
    const o = { when: formatTime(held.requested_at), device: device(from), ip: from.created ? from.created.ip : from.ip };
    return from.good_standing ? M.t("sessions.address.asked_from", o) : M.t("sessions.address.asked_from_unconfirmed", o);
  }
  const MAIL = ["email_link", "email_code"];
  // Unread security items are few (the mail limits); read at most this many pages.
  const ALERT_PAGES = 10;

  // The hub's refusals, in words (§2.6.5, §2.6.3).
  function said(err) {
    const why = err.details && err.details.reason;
    if (why === "not_in_good_standing") return { message: M.t("sessions.refused.not_in_good_standing") };
    if (why === "session_too_new") return { message: M.t("sessions.refused.too_new") };
    if (err.code === "conflict") return { message: M.t("sessions.refused.conflict") };
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

  // What the hub has: the sessions (ended ones too) and the unread security items.
  async function load() {
    const sessions = (await M.api.get("/auth/sessions?ended=true")).items;
    const alerts = await unreadAlerts();
    return { sessions, alerts, current: sessions.find((s) => s.current) || null };
  }

  // Times as instants, on the hub's clock (M.api.now carries its offset).
  const at = (iso) => Date.parse(iso);
  const young = (s, hours) => M.api.now() - at(s.created_at) < hours * HOUR;
  const device = (s) => M.t("sessions.device", { browser: s.browser || M.t("sessions.device.browser_unknown"), os: s.os || M.t("sessions.device.os_unknown") });
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
    if (s.good_standing) return M.t("sessions.cannot_end.confirm_first");
    if (young(cur, 1) && at(s.created_at) < at(cur.created_at)) return M.t("sessions.cannot_end.too_new");
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
  // when the alert is no longer unread; unknown when the list could not be
  // read again.
  const confirmedWords = (alert, words) => (data) => {
    if (!data) return M.t("sessions.confirm.unknown");
    return data.alerts.some((a) => a.id === alert.id) ? M.t("sessions.confirm.refused") : words;
  };

  // The account's section; it redraws in place after each change.
  async function section(ctx) {
    const heading = h("h3", { id: "sessions-heading", class: "sessions-heading", tabindex: "-1" }, M.t("sessions.title"));
    const box = h("section", { class: "sessions", "aria-labelledby": "sessions-heading" });
    const status = M.statusLine();
    status.el.setAttribute("tabindex", "-1");
    const body = h("div");
    append(box, heading,
      h("p", { class: "muted" }, M.t("sessions.hint")),
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
        status.fail(M.t("sessions.not_done"), said(err));
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
      ? h("button", { type: "button", class: "small", "aria-label": M.t("sessions.this_was_me.label", { what: label }),
        onclick: () => act(M.t("sessions.confirming"), () => confirm(alert), confirmedWords(alert, M.t("sessions.confirmed", { what: label }))) }, M.t("sessions.this_was_me"))
      : null);

    async function draw() {
      let data;
      try {
        data = await load();
      } catch (err) {
        append(clear(body), h("p", { class: "send-status failed" }, M.t("sessions.read_failed", { reason: err.message })));
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
            h("strong", null, device(s)), s.current ? h("span", { class: "badge" }, M.t("sessions.this_browser")) : null,
            h("span", { class: s.good_standing ? OK_BADGE : "badge warn" }, s.good_standing ? M.t("sessions.confirmed_badge") : M.t("sessions.unconfirmed_badge")),
            s.second_factor ? h("span", { class: OK_BADGE }, M.t("sessions.second_factor_badge")) : null),
          h("p", { class: "muted" }, lineOf(s, sessions)),
          alert ? h("p", { class: "flag" }, M.t("sessions.alert_open")) : null,
          s.current ? null : h("div", { class: "actions" },
            confirmButton(cur, alert, s, device(s)),
            h("button", { type: "button", class: "small", disabled: why ? true : null, "aria-describedby": why ? "why-" + s.id : null,
              "aria-label": M.t("sessions.end.label", { device: device(s) }),
              onclick: () => act(M.t("sessions.ending"), () => end(s), M.t("sessions.ended_one", { device: device(s) })) }, M.t("sessions.end")),
            why ? h("p", { class: "hint", id: "why-" + s.id }, why) : null));
      };
      // An ended session whose sign-in alert is still unread keeps its This was me.
      const endedRow = (s) => {
        const alert = alertOf(s);
        return h("li", { class: "muted", "data-session": s.id },
          (Object.hasOwn(ENDED_LINES, s.ended_by) ? ENDED_LINES[s.ended_by]({ device: device(s), when: formatTime(s.ended_at) })
            : M.t("sessions.ended.other", { device: device(s), how: s.ended_by, when: formatTime(s.ended_at) })),
          alert ? [" ", M.t("sessions.alert_open"), " ", confirmButton(cur, alert, s, device(s))] : null);
      };
      // Alerts with no session in the list (an address change, §2.6.3).
      const loose = alerts.filter((a) => !(a.target && a.target.type === "session" && sessions.some((s) => s.id === a.target.id)));
      const endedOpen = ended.some(alertOf);
      append(clear(body),
        h("ul", { class: "session-list" }, active.map(row)),
        others.length ? h("div", { class: "actions" },
          h("button", { type: "button", disabled: othersBlocked ? true : null, "aria-describedby": othersBlocked ? "why-end-others" : null,
            onclick: () => act(M.t("sessions.ending"), () => M.api.post("/auth/sessions/end-others", {}),
              cur && !cur.good_standing ? M.t("sessions.ended_others.unconfirmed") : M.t("sessions.ended_others")) }, M.t("sessions.end_others")),
          othersBlocked ? h("p", { class: "hint", id: "why-end-others" }, M.t("sessions.cannot_end.too_new"))
            : cur && !cur.good_standing ? h("p", { class: "hint" }, M.t("sessions.end_others.unconfirmed_hint")) : null) : null,
        loose.length ? [h("h4", null, M.t("sessions.other_alerts")), h("ul", { class: "session-alerts" }, loose.map((a) => h("li", { "data-alert": a.id },
          a.title, h("span", { class: "muted" }, " · " + formatTime(a.at)), " ", confirmButton(cur, a, null, a.title))))] : null,
        ended.length ? h("details", { class: "sessions-ended", open: endedOpen ? true : null },
          h("summary", null, M.t("sessions.ended_list", { count: ended.length })),
          h("ul", null, ended.map(endedRow))) : null,
        await addressChange(ctx, cur, sessions, act));
      return data;
    }
    // Crossing an hour or a day of age changes what this session may do
    // (§2.6.5, §2.6.3): checked each minute, drawn again when it did.
    const ageOf = (data) => (data && data.current ? [young(data.current, 1), young(data.current, 24)].join() : "");
    let last = await draw();
    let lastAge = ageOf(last);
    ctx.every(60 * 1000, async () => {
      if (!last || ageOf(last) === lastAge) return;
      last = await draw();
      lastAge = ageOf(last);
    });
    return { el: box, heading };
  }

  // A held address change (§2.6.3): approve needs good standing and a
  // session at least a day old, reject good standing; both name the change.
  // Which session asked is said: the 24-hour rule exists for a change filed
  // from a session that is not confirmed.
  async function addressChange(ctx, cur, sessions, act) {
    let settings;
    try {
      settings = await M.api.get("/me/notification-settings");
    } catch (err) {
      return null;
    }
    const held = settings && settings.email && settings.email.address_change;
    if (!held) return null;
    const names = { id: held.id, address: held.address };
    const from = sessions.find((s) => s.id === held.session_id);
    const why = !cur || !cur.good_standing ? M.t("sessions.address.confirmed_only")
      : young(cur, 24) ? M.t("sessions.address.too_new") : null;
    return h("div", { class: "address-change", role: "group", "aria-labelledby": "address-change-title" },
      h("h4", { id: "address-change-title" }, M.t("sessions.address.title")),
      h("p", null, held.address === null ? M.t("sessions.address.remove") : M.t("sessions.address.change", { address: held.address }),
        h("span", { class: "muted" }, " · ", !from ? M.t("sessions.address.asked", { when: formatTime(held.requested_at) })
          : askedFrom(held, from))),
      h("div", { class: "actions" },
        h("button", { type: "button", class: "small", disabled: why ? true : null,
          onclick: () => act(M.t("sessions.address.approving"), () => M.api.post("/me/notification-settings/email/address-change/approve", names), M.t("sessions.address.approved")) }, M.t("sessions.address.approve")),
        h("button", { type: "button", class: "small", disabled: !cur || !cur.good_standing ? true : null,
          onclick: () => act(M.t("sessions.address.rejecting"), () => M.api.post("/me/notification-settings/email/address-change/reject", names), M.t("sessions.address.rejected")) }, M.t("sessions.address.reject"))),
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
    const box = h("div", { class: "signin-banner", role: "region", "aria-label": M.t("sessions.banner.label") });
    const status = M.statusLine();
    const run = async (fn) => {
      status.busy("…");
      try {
        await fn();
      } catch (err) {
        status.fail(M.t("sessions.not_done"), said(err));
        return;
      }
      onChange();
    };
    shown.forEach(({ a, s, live }, i) => {
      const why = live.map((x) => cannotEnd(cur, x)).find(Boolean) || null;
      const through = live.filter((x) => x.id !== s.id);
      append(box, h("div", { class: "flag" },
        h("p", null, M.t("sessions.banner.new", { device: device(s), ip: s.created ? s.created.ip : s.ip, when: formatTime(s.created_at) }),
          s.ended_at ? [" ", M.t("sessions.banner.ended_but", { devices: M.fmt.list(through.map(device)) })]
            : through.length ? [" ", M.t("sessions.banner.approved", { devices: M.fmt.list(through.map(device)) })] : null),
        h("button", { type: "button", class: "small", disabled: why ? true : null, "aria-describedby": why ? "banner-why-" + i : null,
          onclick: () => run(async () => { for (const x of live) await end(x); }) }, M.t("sessions.banner.end")), " ",
        mayConfirm(cur, a, s) ? h("button", { type: "button", class: "small", onclick: () => run(() => confirm(a)) }, M.t("sessions.this_was_me")) : null,
        why ? h("p", { class: "hint", id: "banner-why-" + i }, why) : null));
    });
    append(box, status.el);
    return box;
  }

  M.sessions = { section, banner, said, mayConfirm };
})(window.Maity);
