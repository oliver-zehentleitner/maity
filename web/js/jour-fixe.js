// The jour fixe (docs/api.md §20): the team's regular look at how it works.
// In Project settings a human with project:admin sets the series (§20.1) and
// the moderator order (§20.2). The view /<owner>/<slug>/jour-fixe lists the
// rounds, the next slot and the open round, and starts one by hand; a
// round's view (/<owner>/<slug>/jour-fixe/<id>, §16.11) shows its phase, its
// deadlines, who was asked and who was absent, the statement, the exchange
// and the report with its triage, read as every member may (§20.7). Answers
// are never shown here: they stay with their readers (§20.3).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const DAY_WORDS = { mon: () => M.t("jf.day.mon"), tue: () => M.t("jf.day.tue"), wed: () => M.t("jf.day.wed"), thu: () => M.t("jf.day.thu"),
    fri: () => M.t("jf.day.fri"), sat: () => M.t("jf.day.sat"), sun: () => M.t("jf.day.sun") };
  const STATUS = {
    answering: () => M.t("jf.status.answering"), statement: () => M.t("jf.status.statement"), exchange: () => M.t("jf.status.exchange"),
    reporting: () => M.t("jf.status.reporting"), reported: () => M.t("jf.status.reported"), skipped: () => M.t("jf.status.skipped"), missed: () => M.t("jf.status.missed"),
  };
  const SKIP = {
    no_moderator: () => M.t("jf.skip.no_moderator"), too_few: () => M.t("jf.skip.too_few"), round_open: () => M.t("jf.skip.round_open"),
    project_closed: () => M.t("jf.skip.project_closed"), hub_down: () => M.t("jf.skip.hub_down"),
  };
  const ABSENT = { not_available: () => M.t("jf.absent.not_available"), not_online: () => M.t("jf.absent.not_online"),
    no_listening_instance: () => M.t("jf.absent.no_listening_instance") };
  const STEP = { statement: () => M.t("jf.step.statement"), response: () => M.t("jf.step.response"), reply: () => M.t("jf.step.reply"),
    rejoinder: () => M.t("jf.step.rejoinder"), further: () => M.t("jf.step.further") };
  const TRIAGE = { decided: () => M.t("jf.triage.decided"), to_owner: () => M.t("jf.triage.to_owner") };
  const START = { jour_fixe_open: () => M.t("jf.start.open"), project_closed: () => M.t("jf.skip.project_closed"),
    no_moderator: () => M.t("jf.skip.no_moderator"), too_few: () => M.t("jf.skip.too_few"), rate_limited: () => M.t("jf.start.rate_limited") };
  const words = (table, key) => (Object.hasOwn(table, key) ? table[key]() : String(key || ""));
  const MANAGERS = ["owner", "admin"];

  // ---- Project settings: the series (§20.1) ------------------------------

  // policy.jour_fixe as one object, replaced whole by the PATCH (§20.1).
  function settingsForm(ctx, save) {
    const jf = ctx.project.policy.jour_fixe || null;
    const r = (jf && jf.recurrence) || { freq: "weekly", interval: 1, weekdays: ["mon"] };
    const id = (k) => "jf-" + k;
    const enabled = h("input", { type: "checkbox", id: id("enabled") });
    enabled.checked = !!(jf && jf.enabled);
    const freq = h("select", { id: id("freq") }, [["daily", M.t("jf.freq.daily")], ["weekly", M.t("jf.freq.weekly")], ["monthly", M.t("jf.freq.monthly")]]
      .map(([f, label]) => h("option", { value: f }, label)));
    freq.value = r.freq;
    const interval = h("input", { id: id("interval"), type: "number", min: "1", max: "8", step: "1" });
    interval.value = String(r.interval || 1);
    const days = WEEKDAYS.map((d) => {
      const box = h("input", { type: "checkbox", id: id("day-" + d), value: d });
      box.checked = (r.weekdays || []).includes(d);
      return [box, h("label", { class: "check", for: id("day-" + d) }, box, " " + DAY_WORDS[d]()), d];
    });
    const monthBy = h("select", { id: id("month-by") }, h("option", { value: "day" }, M.t("jf.month.by_day")), h("option", { value: "weekday" }, M.t("jf.month.by_weekday")));
    monthBy.value = r.month_weekday ? "weekday" : "day";
    const monthDay = h("input", { id: id("month-day"), type: "number", min: "1", max: "31", step: "1" });
    monthDay.value = String(r.month_day || 1);
    const ordinal = h("select", { id: id("ordinal") }, [["1", M.t("jf.ordinal.1")], ["2", M.t("jf.ordinal.2")], ["3", M.t("jf.ordinal.3")], ["4", M.t("jf.ordinal.4")], ["-1", M.t("jf.ordinal.last")]]
      .map(([v, l]) => h("option", { value: v }, l)));
    ordinal.value = String((r.month_weekday || {}).ordinal || 1);
    const monthWeekday = h("select", { id: id("month-weekday") }, WEEKDAYS.map((d) => h("option", { value: d }, DAY_WORDS[d]())));
    monthWeekday.value = (r.month_weekday || {}).weekday || "mon";
    const time = h("input", { id: id("time"), type: "time" });
    time.value = (jf && jf.time) || "";
    const zones = typeof Intl.supportedValuesOf === "function" ? Intl.supportedValuesOf("timeZone") : [];
    const zoneList = h("datalist", { id: id("zones") }, zones.map((z) => h("option", { value: z })));
    const zone = h("input", { id: id("timezone"), list: id("zones"), autocomplete: "off", spellcheck: "false" });
    zone.value = (jf && jf.timezone) || (Intl.DateTimeFormat().resolvedOptions().timeZone || "");
    const live = (ctx.members || []).filter((x) => !x.removed_at);
    const moderator = h("select", { id: id("moderator") }, h("option", { value: "admin_agent" }, M.t("jf.moderator.admin_agent")),
      live.map((x) => h("option", { value: x.id }, "@" + (x.handle || x.id))));
    moderator.value = (jf && jf.moderator) || "admin_agent";
    const num = (k, lo, hi, def) => {
      const input = h("input", { id: id(k), type: "number", min: String(lo), max: String(hi), step: "1" });
      input.value = String(jf && jf[k] !== undefined ? jf[k] : def);
      return input;
    };
    const answerWin = num("answer_window_minutes", 30, 1440, 120);
    const stepWin = num("step_window_minutes", 30, 1440, 120);
    const reportWin = num("report_window_hours", 1, 72, 12);
    const reason = h("input", { id: id("reason"), placeholder: M.t("jf.reason.placeholder") });
    const error = h("p", { class: "field-error", id: id("error"), role: "alert" });
    // The hub's refusals at the field each names (policy.jour_fixe.<path>, §20.1).
    const fieldErrors = {};
    const at = (path, input) => {
      const e = h("p", { class: "field-error", id: id(path.replace(/\W/g, "-")) + "-error", role: "alert" });
      fieldErrors["policy.jour_fixe." + path] = [e, input];
      input.setAttribute("aria-describedby", e.id);
      return e;
    };
    const FIELD_WORDS = { required: () => M.t("jf.field.required"), format: () => M.t("jf.field.format"), unknown_timezone: () => M.t("jf.field.unknown_timezone"),
      not_a_member: () => M.t("jf.field.not_a_member"), out_of_range: () => M.t("jf.field.out_of_range"), one_of: () => M.t("jf.field.one_of"),
      not_for_freq: () => M.t("jf.field.not_for_freq"), unknown: () => M.t("jf.field.unknown"), invalid: () => M.t("jf.field.invalid") };
    function atFields(err) {
      Object.values(fieldErrors).forEach(([e]) => { e.textContent = ""; });
      const fields = err.code === "invalid" && err.details && err.details.fields;
      if (!fields) return false;
      let first = null;
      Object.entries(fields).forEach(([path, why]) => {
        const hit = fieldErrors[path];
        if (!hit) return;
        hit[0].textContent = Object.hasOwn(FIELD_WORDS, why) ? FIELD_WORDS[why]() : why;
        if (!first) first = hit[1];
      });
      if (first) first.focus();
      return !!first;
    }
    const weekly = h("div", { class: "jf-weekly" }, h("label", { for: id("interval") }, M.t("jf.interval")), interval, at("recurrence.interval", interval),
      h("fieldset", { class: "jf-days" }, h("legend", null, M.t("jf.weekdays")), days.map((d) => d[1])), at("recurrence.weekdays", days[0][0]));
    const monthly = h("div", { class: "jf-monthly" }, h("label", { for: id("month-by") }, M.t("jf.month.by")), monthBy,
      h("label", { for: id("month-day") }, M.t("jf.month.day")), monthDay, at("recurrence.month_day", monthDay),
      h("label", { for: id("ordinal") }, M.t("jf.month.ordinal")), ordinal, h("label", { for: id("month-weekday") }, M.t("jf.month.weekday")), monthWeekday,
      at("recurrence.month_weekday", ordinal));
    const shape = () => {
      weekly.hidden = freq.value !== "weekly";
      monthly.hidden = freq.value !== "monthly";
      monthDay.hidden = monthBy.value !== "day";
      ordinal.hidden = monthWeekday.hidden = monthBy.value !== "weekday";
    };
    freq.addEventListener("change", shape);
    monthBy.addEventListener("change", shape);
    shape();
    function body() {
      const rec = { freq: freq.value };
      if (freq.value === "weekly") { rec.interval = Number(interval.value); rec.weekdays = days.filter((d) => d[0].checked).map((d) => d[2]); }
      if (freq.value === "monthly") {
        if (monthBy.value === "day") rec.month_day = Number(monthDay.value);
        else rec.month_weekday = { ordinal: Number(ordinal.value), weekday: monthWeekday.value };
      }
      return { enabled: enabled.checked, recurrence: rec, time: time.value || null, timezone: zone.value.trim() || null, moderator: moderator.value,
        answer_window_minutes: Number(answerWin.value), step_window_minutes: Number(stepWin.value), report_window_hours: Number(reportWin.value) };
    }
    return h("form", {
      class: "jf-settings project-form",
      onsubmit: (e) => {
        e.preventDefault();
        error.textContent = "";
        const b = body();
        if (b.enabled && (!b.time || !b.timezone)) { error.textContent = M.t("jf.error.time"); (b.time ? zone : time).focus(); return; }
        if (b.recurrence.freq === "weekly" && !b.recurrence.weekdays.length) { error.textContent = M.t("jf.error.weekdays"); days[0][0].focus(); return; }
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy: { jour_fixe: b }, reason: reason.value.trim() }, M.t("jf.title"), atFields);
      },
    },
    h("h2", { class: "panel-title" }, M.t("jf.title")),
    h("p", { class: "hint" }, M.t("jf.settings.hint")),
    h("p", { class: "check" }, enabled, h("label", { for: id("enabled") }, " " + M.t("jf.enabled"))),
    h("label", { for: id("freq") }, M.t("jf.freq")), freq, at("recurrence.freq", freq), weekly, monthly,
    h("label", { for: id("time") }, M.t("jf.time")), time, at("time", time),
    h("label", { for: id("timezone") }, M.t("jf.timezone")), zone, zoneList, at("timezone", zone),
    h("label", { for: id("moderator") }, M.t("jf.moderator")), moderator, at("moderator", moderator),
    h("label", { for: id("answer_window_minutes") }, M.t("jf.answer_window")), answerWin, at("answer_window_minutes", answerWin),
    h("label", { for: id("step_window_minutes") }, M.t("jf.step_window")), stepWin, at("step_window_minutes", stepWin),
    h("label", { for: id("report_window_hours") }, M.t("jf.report_window")), reportWin, at("report_window_hours", reportWin),
    h("label", { for: id("reason") }, M.t("jf.reason")), reason, error,
    h("div", { class: "actions" }, h("button", { type: "submit" }, M.t("jf.save")),
      jf ? h("button", { type: "button", onclick: () => {
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy: { jour_fixe: null }, reason: reason.value.trim() }, M.t("jf.title"));
      } }, M.t("jf.remove")) : null));
  }

  // The moderator order (§20.2): the admin agents, the first present one
  // moderates; an explicit order put first, the rest by time online.
  async function moderatorsPart(ctx) {
    const box = h("section", { class: "jf-moderators", "aria-labelledby": "jf-moderators-title" });
    const status = M.statusLine();
    append(box, h("h3", { id: "jf-moderators-title" }, M.t("jf.moderators.title")), h("p", { class: "hint" }, M.t("jf.moderators.hint")), status.el);
    let state;
    try {
      state = await M.api.get(ctx.base + "/jour-fixe");
    } catch (err) {
      status.fail(M.t("jf.unread"), err);
      return box;
    }
    let order = (state.moderators || []).map((x) => x.member_id);
    let loaded = order.slice();
    // Whether an explicit order is stored, or the default by time online (§20.2).
    let explicit = Array.isArray((ctx.project.policy || {}).jour_fixe_moderators);
    const kind = h("p", { class: "muted jf-order-kind" });
    const sayKind = () => { kind.textContent = explicit ? M.t("jf.moderators.explicit") : M.t("jf.moderators.default"); };
    sayKind();
    const list = h("ol", { class: "jf-order" });
    const reason = h("input", { id: "jf-order-reason", placeholder: M.t("jf.reason.placeholder") });
    const draw = () => append(clear(list), order.length ? order.map((mid, i) => h("li", null, M.dom.memberRef(ctx, mid), " ",
      h("button", { type: "button", class: "small", disabled: i === 0 ? true : null, "aria-label": M.t("jf.moderators.up", { who: M.dom.handleOf(ctx, { id: mid }) || mid }),
        onclick: () => { [order[i - 1], order[i]] = [order[i], order[i - 1]]; draw(); } }, M.t("jf.up")),
      h("button", { type: "button", class: "small", disabled: i === order.length - 1 ? true : null, "aria-label": M.t("jf.moderators.down", { who: M.dom.handleOf(ctx, { id: mid }) || mid }),
        onclick: () => { [order[i + 1], order[i]] = [order[i], order[i + 1]]; draw(); } }, M.t("jf.down"))))
      : h("li", { class: "muted" }, M.t("jf.moderators.none")));
    draw();
    const put = async (value) => {
      // Saving the order shown unchanged would freeze the default as an explicit list.
      if (value !== null && JSON.stringify(value) === JSON.stringify(loaded)) { status.done(); append(status.el, h("span", null, M.t("jf.moderators.unchanged"))); return; }
      if (value === null && !explicit) { status.done(); append(status.el, h("span", null, M.t("jf.moderators.unchanged"))); return; }
      if (!reason.value.trim()) { reason.focus(); return; }
      status.busy(M.t("jf.moderators.saving"));
      try {
        const answer = await M.api.put(ctx.base + "/jour-fixe/moderators", { order: value, reason: reason.value.trim() });
        order = (answer.moderators || []).map((x) => x.member_id);
        loaded = order.slice();
        explicit = value !== null;
        sayKind();
        draw();
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("jf.moderators.saved")));
      } catch (err) {
        status.fail(M.t("jf.moderators.not_saved"), err);
      }
    };
    append(box, kind, list, h("label", { for: "jf-order-reason" }, M.t("jf.reason")), reason,
      h("div", { class: "actions" }, h("button", { type: "button", onclick: () => put(order.slice()) }, M.t("jf.moderators.save")),
        h("button", { type: "button", onclick: () => put(null) }, M.t("jf.moderators.reset"))));
    return box;
  }

  // ---- The view: rounds, the next slot, a start by hand -------------------

  const roundLink = (ctx, r) => ctx.link("jour-fixe", r.id);
  function roundLine(ctx, r) {
    const when = r.opened_at || r.scheduled_for;
    return h("li", { class: "jf-round", "data-round": r.id },
      h("a", { href: roundLink(ctx, r) }, formatTime(when)), " · ", words(STATUS, r.status),
      r.skip_reason ? " · " + words(SKIP, r.skip_reason) : "",
      r.missed_slots ? " · " + M.t("jf.missed_slots", { count: r.missed_slots }) : "");
  }

  async function view(ctx, root, args) {
    if (args && args[0]) { await roundView(ctx, root, args[0]); return; }
    const status = M.statusLine();
    append(root, h("h2", null, M.t("jf.title")), h("p", { class: "muted" }, M.t("jf.intro")), status.el);
    let state, rounds;
    try {
      [state, rounds] = await Promise.all([M.api.get(ctx.base + "/jour-fixe"), M.api.get(ctx.base + "/jour-fixe/rounds")]);
    } catch (err) {
      status.fail(M.t("jf.unread"), err);
      return;
    }
    status.done();
    const policy = state.policy;
    // The rounds are paged (§1.4, §20.9): older ones by the hub's cursor.
    const list = h("ul", { class: "jf-rounds" }, (rounds.items || []).map((r) => roundLine(ctx, r)));
    const more = h("div", { class: "actions" });
    const moreStatus = M.statusLine();
    function showMore(cursor) {
      clear(more);
      if (!cursor) return;
      append(more, h("button", { type: "button", onclick: async () => {
        moreStatus.busy(M.t("jf.rounds.reading"));
        try {
          const page = await M.api.get(ctx.base + "/jour-fixe/rounds?cursor=" + encodeURIComponent(cursor));
          append(list, (page.items || []).map((r) => roundLine(ctx, r)));
          moreStatus.done();
          showMore(page.next_cursor);
        } catch (err) { moreStatus.fail(M.t("jf.unread"), err); append(more, moreStatus.el); }
      } }, M.t("jf.rounds.more")), moreStatus.el);
    }
    const startable = MANAGERS.includes(ctx.trust) && ctx.project.state !== "archived";
    const startStatus = M.statusLine();
    const reason = h("input", { id: "jf-start-reason", placeholder: M.t("jf.reason.placeholder") });
    const start = startable ? h("form", {
      class: "inline-form jf-start",
      onsubmit: async (e) => {
        e.preventDefault();
        if (!reason.value.trim()) { reason.focus(); return; }
        startStatus.busy(M.t("jf.start.busy"));
        try {
          const round = await M.api.post(ctx.base + "/jour-fixe/rounds", { reason: reason.value.trim() });
          M.route.go(roundLink(ctx, round));
        } catch (err) {
          startStatus.fail(M.t("jf.start.failed"), Object.hasOwn(START, err.code) ? { message: START[err.code]() } : err);
        }
      },
    }, h("label", { for: "jf-start-reason" }, M.t("jf.start.reason")), reason, h("button", { type: "submit" }, M.t("jf.start")), startStatus.el) : null;
    append(root,
      h("p", null, policy && policy.enabled
        ? M.t("jf.next", { at: state.next_at ? formatTime(state.next_at) : M.t("jf.next.none") })
        : M.t("jf.not_scheduled")),
      ctx.canAdmin && ctx.me.kind === "human" ? h("p", { class: "hint" }, M.tn("jf.settings_link", { link: h("a", { href: ctx.link("settings") }, M.t("nav.settings")) })) : null,
      state.current_round ? h("p", { class: "jf-current" }, M.t("jf.current"), " ", h("a", { href: roundLink(ctx, state.current_round) }, words(STATUS, state.current_round.status))) : null,
      start,
      h("h3", null, M.t("jf.rounds")),
      (rounds.items || []).length ? list : h("p", { class: "muted" }, M.t("jf.rounds.none")), more);
    showMore(rounds.next_cursor);
  }

  // ---- One round, as a member reads it (§20.7) ---------------------------

  const who = (ctx, id) => (id === "anonymous" ? h("span", { class: "muted" }, M.t("jf.anonymous")) : M.dom.memberRef(ctx, id));
  const redacted = (x) => h("p", { class: "muted jf-redacted" }, M.t("jf.redacted", { at: formatTime(x.redaction.at) })
    + (x.redaction.reason ? " " + M.t("jf.redacted.reason", { reason: x.redaction.reason }) : ""));

  function topicBox(ctx, t, posts) {
    const mine = posts.filter((p) => p.topic_id === t.id);
    return h("li", { class: "jf-topic", "data-topic": t.id },
      h("h4", null, t.title),
      t.redaction ? redacted(t) : [
        t.summary ? h("div", { class: "md" }, M.markdown(t.summary)) : null,
        (t.items || []).length ? h("ul", { class: "jf-items" }, t.items.map((i) => h("li", null, i.redaction ? redacted(i) : [i.text, " — ", who(ctx, i.from)]))) : null,
        (t.proposals || []).length ? h("div", null, h("h5", null, M.t("jf.proposals")),
          h("ul", { class: "jf-proposals" }, t.proposals.map((p) => h("li", null, h("strong", null, p.title), p.reason ? " — " + p.reason : "")))) : null],
      mine.length ? h("ol", { class: "jf-posts" }, mine.map((p) => h("li", { class: "jf-post", "data-post": p.id },
        h("p", { class: "muted" }, words(STEP, p.step), " · ", M.dom.memberRef(ctx, p.by),
          (p.to || []).length ? [" → ", (p.to || []).map((t2, k) => [k ? ", " : "", M.dom.memberRef(ctx, t2)])] : null),
        p.redaction ? redacted(p) : h("div", { class: "md" }, M.markdown(p.body || ""))))) : null);
  }

  function reportBox(ctx, rep) {
    return h("section", { class: "jf-report", "aria-labelledby": "jf-report-title" },
      h("h3", { id: "jf-report-title" }, M.t("jf.report")),
      h("p", { class: "muted" }, rep.source === "hub" ? M.t("jf.report.by_hub") : [M.t("jf.report.by"), " ", M.dom.memberRef(ctx, rep.by)]),
      rep.summary_redaction ? redacted({ redaction: rep.summary_redaction }) : rep.summary ? h("p", null, rep.summary) : null,
      (rep.findings || []).length ? [h("h4", null, M.t("jf.findings")), h("ul", { class: "jf-findings" }, rep.findings.map((f) => h("li", null, f.redaction ? redacted(f) : f.text)))] : null,
      (rep.proposals || []).length ? [h("h4", null, M.t("jf.report.proposals")), h("ul", { class: "jf-report-proposals" }, rep.proposals.map((p) => h("li", { "data-proposal": p.id },
        p.redaction ? redacted(p) : [h("strong", null, p.title), p.reason ? " — " + p.reason : ""],
        h("p", { class: "muted" }, words(TRIAGE, p.triage),
          p.decision ? " · " + (p.decision.outcome === "adopt" ? M.t("jf.decision.adopt") : M.t("jf.decision.reject")) + (p.decision.reason ? ": " + p.decision.reason : "") : "",
          p.humans_only ? " · " + M.t("jf.humans_only") : "",
          p.request_id ? [" · ", h("a", { href: ctx.link("inbox", p.request_id) }, M.t("jf.request"))] : null,
          p.task_id ? [" · ", h("a", { href: ctx.link("tasks", p.task_id) }, M.t("jf.task"))] : null))))] : null);
  }

  async function roundView(ctx, root, id) {
    const crumb = h("nav", { class: "breadcrumb", "aria-label": M.t("jf.breadcrumb") }, h("a", { href: ctx.link("jour-fixe") }, M.t("jf.title")), " / ",
      h("span", { "aria-current": "page" }, id));
    const status = M.statusLine();
    append(root, crumb, status.el);
    let r;
    try {
      r = await M.api.get(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(id));
    } catch (err) {
      status.fail(M.t("jf.round.unread"), err);
      return;
    }
    status.done();
    const open = (r.steps || []).find((s) => s.opened_at && !s.closed_at);
    const due = r.status === "answering" ? r.answers_close_at : r.status === "reporting" ? r.report_due_at : open ? open.closes_at : null;
    append(root,
      h("h2", null, M.t("jf.round.title", { at: formatTime(r.opened_at || r.scheduled_for) })),
      h("p", { class: "jf-phase" }, words(STATUS, r.status), r.skip_reason ? " · " + words(SKIP, r.skip_reason) : "",
        due ? " · " + M.t("jf.due", { at: formatTime(due) }) : ""),
      r.moderator && r.moderator.member_id ? h("p", null, M.t("jf.moderated_by"), " ", M.dom.memberRef(ctx, r.moderator.member_id)) : null,
      typeof r.answers_received === "number" ? h("p", { class: "muted" }, M.t("jf.answers_received", { count: r.answers_received })) : null,
      (r.participants || []).length ? h("p", null, M.t("jf.participants"), " ", r.participants.map((p, k) => [k ? ", " : "", M.dom.memberRef(ctx, p.member_id)])) : null,
      (r.absent || []).length ? h("p", { class: "muted" }, M.t("jf.absent"), " ", r.absent.map((p, k) => [k ? ", " : "", M.dom.memberRef(ctx, p.member_id), " (", words(ABSENT, p.absent_reason), ")"])) : null,
      (r.steps || []).length ? h("ol", { class: "jf-steps" }, r.steps.map((s) => h("li", null, words(STEP, s.kind),
        s.opened_at ? " · " + formatTime(s.opened_at) + (s.closed_at ? " – " + formatTime(s.closed_at) : "") : " · " + M.t("jf.step.pending"),
        s.reason ? " · " + s.reason : ""))) : null,
      r.statement ? h("section", { class: "jf-statement", "aria-labelledby": "jf-statement-title" },
        h("h3", { id: "jf-statement-title" }, M.t("jf.statement")),
        h("ol", { class: "jf-topics" }, (r.statement.topics || []).map((t) => topicBox(ctx, t, r.posts || [])))) : null,
      r.report ? reportBox(ctx, r.report) : null);
    // What this reader may do here (js/jour-fixe-act.js); a change draws the round again.
    if (M.jourFixeAct) append(root, await M.jourFixeAct.parts(ctx, r, () => { clear(root); roundView(ctx, root, id); }));
  }

  M.jourFixe = { settingsForm, moderatorsPart };
  M.views.jourFixe = view;
})(window.Maity);
