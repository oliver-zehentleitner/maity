// The jour fixe's series (docs/api.md §20.1, §20.2). In Project settings a
// human with project:admin keeps the series of the circles `humans` and `all`
// and deletes an owner's series; the owner keeps their own series. Per series:
// topic, circle, schedule, windows, and its moderators, granted with consent
// (a grant waits in pending_moderators for the agent owner's and a keeper's
// consent) and ended. The view js/jour-fixe.js reads the same helpers to say
// who may start a round.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const DAY = { mon: () => M.t("jf.day.mon"), tue: () => M.t("jf.day.tue"), wed: () => M.t("jf.day.wed"), thu: () => M.t("jf.day.thu"),
    fri: () => M.t("jf.day.fri"), sat: () => M.t("jf.day.sat"), sun: () => M.t("jf.day.sun") };
  const FREQ = { daily: () => M.t("jf.freq.daily"), weekly: () => M.t("jf.freq.weekly"), monthly: () => M.t("jf.freq.monthly") };
  const ORDINAL = { 1: () => M.t("jf.ordinal.1"), 2: () => M.t("jf.ordinal.2"), 3: () => M.t("jf.ordinal.3"), 4: () => M.t("jf.ordinal.4"), "-1": () => M.t("jf.ordinal.last") };
  const CIRCLE = { owner: () => M.t("jfs.circle.owner"), humans: () => M.t("jfs.circle.humans"), all: () => M.t("jfs.circle.all") };
  const dayWord = (d) => DAY[d]();
  const FIELD_WORDS = { required: () => M.t("jf.field.required"), format: () => M.t("jf.field.format"), unknown_timezone: () => M.t("jf.field.unknown_timezone"),
    not_a_member: () => M.t("jf.field.not_a_member"), out_of_range: () => M.t("jf.field.out_of_range"), one_of: () => M.t("jf.field.one_of"),
    not_for_freq: () => M.t("jf.field.not_for_freq"), unknown: () => M.t("jf.field.unknown"), invalid: () => M.t("jf.field.invalid"),
    too_many: () => M.t("jfs.field.too_many"), fixed: () => M.t("jfs.field.fixed"), too_long: () => M.t("jfs.field.too_long") };
  const REFUSALS = { not_series_keeper: () => M.t("jfs.refused.not_series_keeper"), circle_owner_gone: () => M.t("jfs.refused.circle_owner_gone") };

  // A series a reader may not see in full: an admin is told it exists, without its topic (§20.1).
  const isPrivate = (s) => typeof s.topic !== "string";
  const human = (ctx) => ctx.me.kind === "human";
  // The keepers (§20.1): an owner series' circle owner, else the humans with project:admin.
  const keeps = (ctx, s) => human(ctx) && (isPrivate(s) || s.circle === "owner" ? ctx.me.id === s.circle_owner : ctx.canAdmin);
  // An admin deletes an owner's series, never reads it.
  const mayDelete = (ctx, s) => keeps(ctx, s) || (human(ctx) && ctx.canAdmin && (isPrivate(s) || s.circle === "owner"));
  const holds = (ctx, s) => (s.moderators || []).some((x) => x.member_id === ctx.me.id);
  // A round by hand is for the keepers and the moderators (§20.1).
  const mayStart = (ctx, s) => !isPrivate(s) && (keeps(ctx, s) || holds(ctx, s));
  const handle = (ctx, id) => {
    const m = ctx.memberById && ctx.memberById[id];
    return "@" + ((m && M.dom.handleOf(ctx, m)) || id);
  };

  function said(err) {
    const d = err.details || {};
    const key = [d.reason, err.code].find((k) => k && Object.hasOwn(REFUSALS, k));
    return key ? { message: REFUSALS[key]() } : err;
  }

  function circleText(ctx, s) {
    if (s.circle === "owner" || (isPrivate(s) && s.circle_owner)) return M.t("jfs.circle.owner_of", { who: handle(ctx, s.circle_owner) });
    return s.circle === "humans" || s.circle === "all" ? CIRCLE[s.circle]() : "";
  }

  // The schedule as a sentence: "Every 2 weeks on Monday, Thursday at 10:00 (Europe/Vienna)".
  function scheduleText(s) {
    const r = s.recurrence;
    if (!r) return M.t("jfs.sched.none");
    const days = (r.weekdays || []).map(dayWord).join(", ");
    const what = r.freq === "daily" ? M.t("jfs.sched.daily")
      : r.freq === "weekly" ? ((r.interval || 1) > 1 ? M.t("jfs.sched.weekly_n", { n: r.interval, days }) : M.t("jfs.sched.weekly", { days }))
        : r.month_weekday ? M.t("jfs.sched.monthly_weekday", { ordinal: ORDINAL[r.month_weekday.ordinal](),
          weekday: dayWord(r.month_weekday.weekday) })
          : M.t("jfs.sched.monthly_day", { day: r.month_day });
    return s.time ? M.t("jfs.sched.at", { what, time: s.time, zone: s.timezone || "" }) : what;
  }

  // ---- The form: create and edit ----------------------------------------

  // series: null to create one, else the series to change (its circle is fixed, §20.1).
  function seriesForm(ctx, series, done, cancel) {
    const s = series || {};
    const r = s.recurrence || { freq: "weekly", interval: 1, weekdays: ["mon"] };
    const id = (k) => "jfs-" + k;
    const topic = h("input", { id: id("topic"), maxlength: "300", autocomplete: "off" });
    topic.value = s.topic || "";
    const circle = h("select", { id: id("circle"), disabled: series ? true : null }, Object.keys(CIRCLE).map((c) => h("option", { value: c }, CIRCLE[c]())));
    circle.value = s.circle || "all";
    const humans = (ctx.members || []).filter((x) => !x.removed_at && x.kind === "human");
    const circleOwner = h("select", { id: id("circle_owner"), disabled: series ? true : null }, humans.map((x) => h("option", { value: x.id }, handle(ctx, x.id))));
    circleOwner.value = s.circle_owner || (humans.some((x) => x.id === ctx.me.id) ? ctx.me.id : (humans[0] || {}).id || "");
    const enabled = h("input", { type: "checkbox", id: id("enabled") });
    enabled.checked = !!s.enabled;
    const freq = h("select", { id: id("freq") }, Object.keys(FREQ).map((f) => h("option", { value: f }, FREQ[f]())));
    freq.value = r.freq;
    const interval = h("input", { id: id("interval"), type: "number", min: "1", max: "8", step: "1" });
    interval.value = String(r.interval || 1);
    const days = WEEKDAYS.map((d) => {
      const box = h("input", { type: "checkbox", id: id("day-" + d), value: d });
      box.checked = (r.weekdays || []).includes(d);
      return [box, h("label", { class: "check", for: id("day-" + d) }, box, " " + dayWord(d)), d];
    });
    const monthBy = h("select", { id: id("month-by") }, h("option", { value: "day" }, M.t("jf.month.by_day")), h("option", { value: "weekday" }, M.t("jf.month.by_weekday")));
    monthBy.value = r.month_weekday ? "weekday" : "day";
    const monthDay = h("input", { id: id("month-day"), type: "number", min: "1", max: "31", step: "1" });
    monthDay.value = String(r.month_day || 1);
    const ordinal = h("select", { id: id("ordinal") }, Object.keys(ORDINAL).map((v) => h("option", { value: v }, ORDINAL[v]())));
    ordinal.value = String((r.month_weekday || {}).ordinal || 1);
    const monthWeekday = h("select", { id: id("month-weekday") }, WEEKDAYS.map((d) => h("option", { value: d }, dayWord(d))));
    monthWeekday.value = (r.month_weekday || {}).weekday || "mon";
    const time = h("input", { id: id("time"), type: "time" });
    time.value = s.time || "";
    const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
    const zoneList = h("datalist", { id: id("zones") }, zones.map((z) => h("option", { value: z })));
    const zone = h("input", { id: id("timezone"), list: id("zones"), autocomplete: "off", spellcheck: "false" });
    zone.value = s.timezone || (Intl.DateTimeFormat().resolvedOptions().timeZone || "");
    const num = (k, lo, hi, def) => {
      const input = h("input", { id: id(k), type: "number", min: String(lo), max: String(hi), step: "1" });
      input.value = String(s[k] !== undefined ? s[k] : def);
      return input;
    };
    const answerWin = num("answer_window_minutes", 30, 1440, 120);
    const stepWin = num("step_window_minutes", 30, 1440, 120);
    const reportWin = num("report_window_hours", 1, 72, 12);
    const reason = h("input", { id: id("reason"), placeholder: M.t("jf.reason.placeholder") });
    const error = h("p", { class: "field-error", id: id("error"), role: "alert" });
    const status = M.statusLine();
    // The hub's refusals at the field each names (§20.1).
    const fieldErrors = {};
    const at = (path, input) => {
      const e = h("p", { class: "field-error", id: id(path.replace(/\W/g, "-")) + "-error", role: "alert" });
      fieldErrors[path] = [e, input];
      input.setAttribute("aria-describedby", e.id);
      return e;
    };
    // The status line's text for refusals with no field of their own, or false when the hub named none.
    function atFields(err) {
      Object.values(fieldErrors).forEach(([e]) => { e.textContent = ""; });
      const fields = err.code === "invalid" && err.details && err.details.fields;
      if (!fields) return false;
      let first = null;
      const rest = [];
      Object.entries(fields).forEach(([path, why]) => {
        const text = Object.hasOwn(FIELD_WORDS, why) ? FIELD_WORDS[why]() : why;
        const hit = fieldErrors[path];
        if (!hit) { rest.push(path + ": " + text); return; }
        hit[0].textContent = text;
        if (!first) first = hit[1];
      });
      if (first) first.focus();
      if (!first && !rest.length) return false;
      return [first ? M.t("settings.see_fields") : null].concat(rest).filter(Boolean).join("; ");
    }
    const ownerRow = h("div", { class: "jfs-owner" }, h("label", { for: id("circle_owner") }, M.t("jfs.circle_owner")), circleOwner, at("circle_owner", circleOwner));
    const weekly = h("div", { class: "jf-weekly" }, h("label", { for: id("interval") }, M.t("jf.interval")), interval, at("recurrence.interval", interval),
      h("fieldset", { class: "jf-days" }, h("legend", null, M.t("jf.weekdays")), days.map((d) => d[1])), at("recurrence.weekdays", days[0][0]));
    const monthly = h("div", { class: "jf-monthly" }, h("label", { for: id("month-by") }, M.t("jf.month.by")), monthBy,
      h("label", { for: id("month-day") }, M.t("jf.month.day")), monthDay, at("recurrence.month_day", monthDay),
      h("label", { for: id("ordinal") }, M.t("jf.month.ordinal")), ordinal, h("label", { for: id("month-weekday") }, M.t("jf.month.weekday")), monthWeekday,
      at("recurrence.month_weekday", ordinal));
    const shape = () => {
      ownerRow.hidden = circle.value !== "owner";
      weekly.hidden = freq.value !== "weekly";
      monthly.hidden = freq.value !== "monthly";
      monthDay.hidden = monthBy.value !== "day";
      ordinal.hidden = monthWeekday.hidden = monthBy.value !== "weekday";
    };
    [circle, freq, monthBy].forEach((el) => el.addEventListener("change", shape));
    shape();
    function body() {
      const rec = { freq: freq.value };
      if (freq.value === "weekly") { rec.interval = Number(interval.value); rec.weekdays = days.filter((d) => d[0].checked).map((d) => d[2]); }
      if (freq.value === "monthly") {
        if (monthBy.value === "day") rec.month_day = Number(monthDay.value);
        else rec.month_weekday = { ordinal: Number(ordinal.value), weekday: monthWeekday.value };
      }
      const b = { topic: topic.value.trim(), enabled: enabled.checked, recurrence: rec, time: time.value || null, timezone: zone.value.trim() || null,
        answer_window_minutes: Number(answerWin.value), step_window_minutes: Number(stepWin.value), report_window_hours: Number(reportWin.value),
        reason: reason.value.trim() };
      if (!series) { b.circle = circle.value; if (circle.value === "owner") b.circle_owner = circleOwner.value; }
      return b;
    }
    return h("form", {
      class: "jf-series-form project-form",
      "data-series": s.id || "",
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const b = body();
        if (!b.topic) { error.textContent = M.t("jfs.error.topic"); topic.focus(); return; }
        if (b.enabled && (!b.time || !b.timezone)) { error.textContent = M.t("jf.error.time"); (b.time ? zone : time).focus(); return; }
        if (b.recurrence.freq === "weekly" && !b.recurrence.weekdays.length) { error.textContent = M.t("jf.error.weekdays"); days[0][0].focus(); return; }
        if (!b.reason) { reason.focus(); return; }
        status.busy(M.t("jfs.saving"));
        try {
          if (series) await M.api.patch(ctx.base + "/jour-fixe/series/" + encodeURIComponent(series.id), b);
          else await M.api.post(ctx.base + "/jour-fixe/series", b);
          status.done();
          done(M.t("jfs.saved"));
        } catch (err) {
          const atField = atFields(err);
          status.fail(M.t("jfs.not_saved"), atField ? { message: atField } : said(err));
        }
      },
    },
    h("h3", null, series ? M.t("jfs.edit_title") : M.t("jfs.new")),
    h("label", { for: id("topic") }, M.t("jfs.topic")), topic, at("topic", topic), at("series", topic),
    h("label", { for: id("circle") }, M.t("jfs.circle")), circle, at("circle", circle), ownerRow,
    h("p", { class: "check" }, enabled, h("label", { for: id("enabled") }, " " + M.t("jf.enabled"))),
    h("label", { for: id("freq") }, M.t("jf.freq")), freq, at("recurrence.freq", freq), weekly, monthly,
    h("label", { for: id("time") }, M.t("jf.time")), time, at("time", time),
    h("label", { for: id("timezone") }, M.t("jf.timezone")), zone, zoneList, at("timezone", zone),
    h("label", { for: id("answer_window_minutes") }, M.t("jf.answer_window")), answerWin, at("answer_window_minutes", answerWin),
    h("label", { for: id("step_window_minutes") }, M.t("jf.step_window")), stepWin, at("step_window_minutes", stepWin),
    h("label", { for: id("report_window_hours") }, M.t("jf.report_window")), reportWin, at("report_window_hours", reportWin),
    h("label", { for: id("reason") }, M.t("jf.reason")), reason, at("reason", reason), error, status.el,
    h("div", { class: "actions" }, h("button", { type: "button", onclick: cancel }, M.t("jfs.cancel")), h("button", { type: "submit" }, M.t("jfs.save"))));
  }

  // ---- A member's part in a series: opting out, the report list (§20.2) --

  // own_agents: one entry per agent of the caller, as a list of {member_id, opted_out, report_recipient}
  // or a map by member id (the contract names the field, not its shape).
  const ownAgents = (s) => (Array.isArray(s.own_agents) ? s.own_agents
    : Object.entries(s.own_agents || {}).map(([id, v]) => Object.assign({ member_id: id }, v)));
  const recipientIds = (s) => (s.report_recipients || []).map((x) => (typeof x === "string" ? x : x.member_id));

  // Who is shown, from what the hub sends: the caller's own flags, each of their agents' (an owner acts
  // for them with ?member=), and for a keeper the report list. `done` draws the view again.
  function participation(ctx, s, done) {
    const status = M.statusLine();
    const base = ctx.base + "/jour-fixe/series/" + encodeURIComponent(s.id);
    // The flag's switch: PUT sets it, DELETE takes it back (§20.2), for the member itself or one's own agent.
    const toggle = (memberId, kind, on) => async () => {
      const path = base + "/" + kind + (memberId === ctx.me.id ? "" : "?member=" + encodeURIComponent(memberId));
      status.busy(M.t("jfs.part.saving"));
      try {
        await (on ? M.api.del(path) : M.api.put(path));
        status.done();
        done();
      } catch (err) {
        status.fail(M.t("jfs.not_done"), said(err));
      }
    };
    const row = (memberId, optedOut, recipient) => h("li", { class: "jf-part", "data-member": memberId }, M.dom.memberRef(ctx, memberId), " · ",
      h("span", { class: "jf-part-state" }, optedOut ? M.t("jfs.part.out") : M.t("jfs.part.in")), " ",
      h("button", { type: "button", class: "small jf-optout", onclick: toggle(memberId, "opt-out", optedOut) }, optedOut ? M.t("jfs.part.opt_in") : M.t("jfs.part.opt_out")), " · ",
      h("span", { class: "jf-report-state" }, recipient ? M.t("jfs.report.on") : M.t("jfs.report.off")), " ",
      h("button", { type: "button", class: "small jf-report-toggle", onclick: toggle(memberId, "report", recipient) }, recipient ? M.t("jfs.report.remove") : M.t("jfs.report.add")));
    const rows = [];
    if (typeof s.opted_out === "boolean") rows.push(row(ctx.me.id, s.opted_out, !!s.report_recipient));
    ownAgents(s).forEach((a) => rows.push(row(a.member_id, !!a.opted_out, !!a.report_recipient)));
    const keeper = Array.isArray(s.report_recipients);
    if (!rows.length && !keeper) return null;
    return h("div", { class: "jf-participation" },
      rows.length ? [h("h4", null, M.t("jfs.part.title")), h("ul", { class: "jf-part-list" }, rows)] : null,
      keeper ? h("p", { class: "muted jf-recipients" }, M.t("jfs.report.list"), " ",
        recipientIds(s).length ? recipientIds(s).map((id, k) => [k ? ", " : "", M.dom.memberRef(ctx, id)]) : M.t("jfs.report.nobody")) : null,
      status.el);
  }

  // ---- Project settings: the list, its moderators ------------------------

  function seriesItem(ctx, s, reload, say) {
    const priv = isPrivate(s);
    const reason = h("input", { id: "jfs-reason-" + s.id, placeholder: M.t("jf.reason.placeholder"), "aria-label": M.t("jf.reason") });
    const status = M.statusLine();
    // A write of this series with the row's reason, then the list again.
    // Ending a moderator's right takes no reason and no body (§20.2): `reasoned` false.
    const act = (busy, run, ok, reasoned = true) => async () => {
      if (reasoned && !reason.value.trim()) { reason.focus(); return; }
      status.busy(busy);
      try {
        await run(reason.value.trim());
        status.done();
        await reload(ok);
      } catch (err) {
        status.fail(M.t("jfs.not_done"), said(err));
      }
    };
    const base = ctx.base + "/jour-fixe/series/" + encodeURIComponent(s.id);
    const head = h("p", { class: "jfs-head" }, h("strong", null, priv ? M.t("jfs.private", { who: handle(ctx, s.circle_owner) }) : s.topic));
    const facts = h("p", { class: "muted jfs-facts" }, priv ? "" : circleText(ctx, s) + " · ", s.enabled ? M.t("jfs.on") : M.t("jfs.off"), " · ", scheduleText(s));
    const li = h("li", { class: "jf-series", "data-series": s.id }, head, facts);
    if (!priv) append(li, moderators(ctx, s, act, base, say));
    if (mayDelete(ctx, s)) {
      append(li, h("div", { class: "actions jfs-actions" }, h("label", { for: reason.id }, M.t("jf.reason")), reason,
        keeps(ctx, s) && !priv ? h("button", { type: "button", class: "small jfs-edit" }, M.t("jfs.edit")) : null,
        mayDelete(ctx, s) ? h("button", { type: "button", class: "small jfs-delete", onclick: act(M.t("jfs.deleting"), (why) => M.api.del(base, { reason: why }), M.t("jfs.deleted")) },
          M.t("jfs.delete")) : null), status.el);
    }
    return li;
  }

  // The moderators of one series, the pending grants, and the form to grant (§20.2).
  function moderators(ctx, s, act, base, say) {
    const mods = s.moderators || [], pending = s.pending_moderators || [];
    const box = h("div", { class: "jfs-moderators" }, h("h4", null, M.t("jfs.moderators")));
    const end = (x, label) => keeps(ctx, s) ? h("button", { type: "button", class: "small jfs-end", "aria-label": M.t("jfs.end_of", { who: handle(ctx, x.member_id) }),
      onclick: () => act(M.t("jfs.ending"), () => M.api.del(base + "/moderators/" + encodeURIComponent(x.member_id)), M.t("jfs.ended"), false)() }, label) : null;
    append(box, h("ul", { class: "jf-moderators-list" },
      mods.map((x) => h("li", { "data-member": x.member_id }, M.dom.memberRef(ctx, x.member_id), " ", end(x, M.t("jfs.end")))),
      pending.map((x) => h("li", { class: "jf-pending", "data-member": x.member_id }, M.dom.memberRef(ctx, x.member_id), " · ",
        h("span", { class: "muted" }, M.t("jfs.pending")), " ", end(x, M.t("jfs.end")))),
      mods.length || pending.length ? null : h("li", { class: "muted" }, M.t("jfs.moderators.none"))));
    if (!keeps(ctx, s)) return box;
    // A human grants it to themselves only; an agent to its owner's or another's (§20.2).
    const taken = new Set(mods.concat(pending).map((x) => x.member_id));
    const options = (ctx.members || []).filter((x) => !x.removed_at && !taken.has(x.id) && (x.kind === "agent" || x.id === ctx.me.id));
    if (!options.length) return box;
    const pick = h("select", { class: "jfs-grant-member", id: "jfs-grant-" + s.id, "aria-label": M.t("jfs.grant_to") }, options.map((x) => h("option", { value: x.id }, handle(ctx, x.id))));
    const grant = act(M.t("jfs.granting"), (why) => M.api.post(base + "/moderators", { member_id: pick.value, reason: why }),
      () => say(pick.value, s.id));
    append(box, h("div", { class: "actions" }, h("label", { for: pick.id }, M.t("jfs.grant_to")), pick, h("button", { type: "button", class: "small jfs-grant", onclick: grant }, M.t("jfs.grant"))));
    return box;
  }

  function settingsPart(ctx) {
    const box = h("section", { class: "jf-series-settings", "aria-labelledby": "jfs-title" });
    const status = M.statusLine();
    const list = h("ul", { class: "jf-series-list" });
    const slot = h("div", { class: "jfs-form-slot" });
    const note = h("p", { class: "jfs-note", role: "status" });
    const create = h("button", { type: "button", class: "jfs-new", onclick: () => open(null) }, M.t("jfs.new"));
    append(box, h("h2", { class: "panel-title", id: "jfs-title" }, M.t("jfs.title")), h("p", { class: "hint" }, M.t("jfs.hint")), status.el, note, list, slot, h("div", { class: "actions" }, create));
    let items = [];
    function open(s) {
      const close = () => { clear(slot); create.hidden = false; };
      create.hidden = true;
      append(clear(slot), seriesForm(ctx, s, (text) => { close(); load(text); }, close));
      slot.querySelector("input").focus();
    }
    // What a grant became, read from the series as the hub has it (a 201 holds the right, a 202 waits).
    const say = (member, series) => {
      const s = items.find((x) => x.id === series) || {};
      const who = handle(ctx, member);
      return (s.moderators || []).some((x) => x.member_id === member) ? M.t("jfs.grant.done", { who }) : M.t("jfs.grant.waiting", { who });
    };
    async function load(text) {
      try {
        items = (await M.api.get(ctx.base + "/jour-fixe")).series || [];
      } catch (err) {
        status.fail(M.t("jf.unread"), err);
        return;
      }
      status.done();
      const edit = (s) => open(s);
      append(clear(list), items.length ? items.map((s) => {
        const li = seriesItem(ctx, s, load, say);
        const btn = li.querySelector(".jfs-edit");
        if (btn) btn.addEventListener("click", () => edit(s));
        return li;
      }) : h("li", { class: "muted" }, M.t("jfs.none")));
      note.textContent = (typeof text === "function" ? text() : text) || "";
    }
    load();
    return box;
  }

  M.jourFixeSeries = { settingsPart, participation, scheduleText, circleText, isPrivate, keeps, mayStart, handle };
})(window.Maity);
