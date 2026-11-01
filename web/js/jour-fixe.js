// The jour fixe (docs/api.md §20): the team's regular look at how it works.
// The series (§20.1) and their moderators are kept in Project settings
// (js/jour-fixe-series.js). The view /<owner>/<slug>/jour-fixe lists the
// rounds per series with its topic, the next slot, the open round, and starts
// a round of a series by hand for its keepers and moderators; a round's view
// (/<owner>/<slug>/jour-fixe/<id>, §16.11) shows its phase, its deadlines, who
// was asked and who was absent, the statement, the exchange and the report
// with its triage, read as every member may (§20.7). A series of one owner is
// that owner's own: whatever the hub sends of it is shown, nothing is guessed.
// Answers are never shown here: they stay with their readers (§20.3).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

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
    no_moderator: () => M.t("jf.skip.no_moderator"), too_few: () => M.t("jf.skip.too_few"), rate_limited: () => M.t("jf.start.rate_limited"),
    circle_owner_gone: () => M.t("jfs.refused.circle_owner_gone"), not_series_keeper: () => M.t("jfs.refused.not_series_keeper") };
  const words = (table, key) => (Object.hasOwn(table, key) ? table[key]() : String(key || ""));

  // ---- The view: rounds, the next slot, a start by hand -------------------

  const roundLink = (ctx, r) => ctx.link("jour-fixe", r.id);
  function roundLine(ctx, r) {
    const when = r.opened_at || r.scheduled_for;
    return h("li", { class: "jf-round", "data-round": r.id },
      h("a", { href: roundLink(ctx, r) }, formatTime(when)), " · ", words(STATUS, r.status),
      r.skip_reason ? " · " + words(SKIP, r.skip_reason) : "",
      r.missed_slots ? " · " + M.t("jf.missed_slots", { count: r.missed_slots }) : "");
  }

  // A refusal to start: the hub's 409 code, or its reason (a series whose owner left, §20.1).
  const startWords = (err) => {
    const key = [err.code, (err.details || {}).reason].find((k) => k && Object.hasOwn(START, k));
    return key ? { message: START[key]() } : err;
  };

  // One series: its topic, circle and schedule, the next slot, the open round, a start by hand, then its rounds.
  function seriesBlock(ctx, s, redraw) {
    const series = M.jourFixeSeries;
    const list = h("ul", { class: "jf-rounds" });
    const none = h("p", { class: "muted" }, M.t("jf.rounds.none"));
    const box = h("section", { class: "jf-series-block", "data-series": s.id, "aria-labelledby": "jf-series-" + s.id }, h("h3", { class: "jf-series-title", id: "jf-series-" + s.id }, s.topic || s.id));
    if (s.circle) append(box, h("p", { class: "muted" }, series.circleText(ctx, s), s.enabled ? " · " + series.scheduleText(s) : ""));
    append(box, h("p", { class: "jf-next" }, s.enabled
      ? M.t("jf.next", { at: s.next_at ? formatTime(s.next_at) : M.t("jf.next.none") }) : M.t("jf.not_scheduled")));
    append(box, series.participation(ctx, s, redraw));
    const open = s.current_round;
    if (open) append(box, h("p", { class: "jf-current" }, M.t("jf.current"), " ", h("a", { href: roundLink(ctx, open) }, words(STATUS, open.status))));
    if (series.mayStart(ctx, s) && ctx.project.state !== "archived") {
      const startStatus = M.statusLine();
      const reason = h("input", { id: "jf-start-reason-" + s.id, placeholder: M.t("jf.reason.placeholder") });
      append(box, h("form", {
        class: "inline-form jf-start",
        "data-series": s.id,
        onsubmit: async (e) => {
          e.preventDefault();
          if (!reason.value.trim()) { reason.focus(); return; }
          startStatus.busy(M.t("jf.start.busy"));
          try {
            const round = await M.api.post(ctx.base + "/jour-fixe/series/" + encodeURIComponent(s.id) + "/rounds", { reason: reason.value.trim() });
            M.route.go(roundLink(ctx, round));
          } catch (err) {
            startStatus.fail(M.t("jf.start.failed"), startWords(err));
          }
        },
      }, h("label", { for: reason.id }, M.t("jf.start.reason")), reason, h("button", { type: "submit" }, M.t("jf.start")), startStatus.el));
    }
    append(box, list, none);
    return { box, add: (r) => { append(list, roundLine(ctx, r)); none.hidden = true; } };
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
    const all = state.series || [];
    const redraw = () => { clear(root); view(ctx, root, args); };
    // Rounds go to their series' block (§20.7: the round names it); one of a series gone gets a block of its topic.
    const blocks = new Map();
    let privates = 0;
    const holder = h("div", { class: "jf-series-blocks" });
    const blockFor = (id, s) => {
      if (!blocks.has(id)) { const b = seriesBlock(ctx, s, redraw); blocks.set(id, b); append(holder, b.box); }
      return blocks.get(id);
    };
    all.forEach((s) => {
      // An owner's series an admin may not read: that it exists, its schedule, nothing of it.
      if (!M.jourFixeSeries.isPrivate(s)) { blockFor(s.id, s); return; }
      privates += 1;
      append(holder, h("p", { class: "muted jf-private", "data-series": s.id }, M.t("jfs.private", { who: M.jourFixeSeries.handle(ctx, s.circle_owner) }), " ",
        M.jourFixeSeries.scheduleText(s)));
    });
    const place = (r) => blockFor(r.series_id || "", { id: r.series_id || "", topic: r.topic || null }).add(r);
    (rounds.items || []).forEach(place);
    // The rounds are paged (§1.4, §20.9): older ones by the hub's cursor.
    const more = h("div", { class: "actions" });
    const moreStatus = M.statusLine();
    function showMore(cursor) {
      clear(more);
      if (!cursor) return;
      append(more, h("button", { type: "button", onclick: async () => {
        moreStatus.busy(M.t("jf.rounds.reading"));
        try {
          const page = await M.api.get(ctx.base + "/jour-fixe/rounds?cursor=" + encodeURIComponent(cursor));
          (page.items || []).forEach(place);
          moreStatus.done();
          showMore(page.next_cursor);
        } catch (err) { moreStatus.fail(M.t("jf.unread"), err); append(more, moreStatus.el); }
      } }, M.t("jf.rounds.more")), moreStatus.el);
    }
    append(root,
      ctx.canAdmin && ctx.me.kind === "human" ? h("p", { class: "hint" }, M.tn("jf.settings_link", { link: h("a", { href: ctx.link("settings") }, M.t("nav.settings")) })) : null,
      holder,
      blocks.size || privates ? null : h("p", { class: "muted" }, M.t("jfs.none")), more);
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
      r.topic ? h("p", { class: "jf-topic-line" }, M.t("jf.round.topic", { topic: r.topic })) : null,
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

  M.views.jourFixe = view;
})(window.Maity);
