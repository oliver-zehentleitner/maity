// What a person does in a jour fixe round (docs/api.md §20.3–§20.6, §20.8),
// drawn under the round's view (js/jour-fixe.js) for whoever may do it:
// a participant answers while the window is open, by name or anonymously
// with the limits of anonymity said first (§20.4), reads and withdraws its
// own answer; the moderator and the humans of the admin team read the
// answers and redact one; a human moderator writes the statement, adds a
// further step and writes the report with its triage; an eligible member
// posts once per topic in the open step; a human invited to the round, or
// one of the admin team, redacts the report's summary, a finding or a
// proposal. Every refusal of the hub is said in words.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const FIELDS = [["went_well", () => M.t("jfa.q.went_well")], ["went_badly", () => M.t("jfa.q.went_badly")], ["would_help", () => M.t("jfa.q.would_help")]];
  const TEXT_MAX = 4096, ALL_MAX = 12288;
  // Bytes of UTF-8, as the hub counts them: each escaped byte one.
  const bytes = (s) => encodeURIComponent(s || "").replace(/%[0-9A-F]{2}/g, "x").length;
  const REFUSALS = {
    jour_fixe_answered: () => M.t("jfa.refused.answered"), jour_fixe_state: () => M.t("jfa.refused.state"),
    not_participant: () => M.t("jfa.refused.not_participant"), not_eligible: () => M.t("jfa.refused.not_eligible"),
    not_moderator: () => M.t("jfa.refused.not_moderator"), may_not_decide: () => M.t("jfa.refused.may_not_decide"),
    humans_only: () => M.t("jfa.refused.humans_only"), empty: () => M.t("jfa.refused.empty"), too_long: () => M.t("jfa.refused.too_long"),
    not_an_answerer: () => M.t("jfa.refused.not_an_answerer"), too_many_proposals: () => M.t("jfa.refused.too_many_proposals"),
    redacted_statement_proposal: () => M.t("jfa.refused.redacted_statement_proposal"),
    not_owner_preferences: () => M.t("jfa.refused.not_owner_preferences"), unknown_version: () => M.t("jfa.refused.unknown_version"),
    not_addressed: () => M.t("jfa.refused.not_addressed"), not_a_participant: () => M.t("jfa.refused.not_a_participant"),
    unknown_topic: () => M.t("jfa.refused.unknown_topic"),
  };
  // The hub's refusal in words: its code, its reason, or the reason of a field.
  function said(err) {
    const d = err.details || {};
    const field = d.fields && Object.values(d.fields)[0];
    const key = [d.reason, field, err.code].find((k) => k && Object.hasOwn(REFUSALS, k));
    if (key) return { message: REFUSALS[key]() };
    // A scope the caller lacks (a redaction needs events:admin, §20.8), said by its name.
    if (err.code === "forbidden" && d.scope) return { message: M.t("jfa.refused.scope", { scope: d.scope }) };
    return err;
  }

  // Rounds whose anonymous answer was withdrawn in this tab: the hub keeps its tag, so no second
  // answer is possible there (§20.4), and the form is not offered again.
  const withdrawnHere = new Set();
  const adminTeam = (ctx) => ctx.me.kind === "human" && ["owner", "admin"].includes(ctx.trust) && ctx.role !== "proxy";
  const ids = (list) => (list || []).map((x) => x.member_id);

  // A redaction with its reason, asked for in place (§20.8).
  function redactButton(ctx, r, target, done) {
    const box = h("span", { class: "jfa-redact" });
    const open = h("button", { type: "button", class: "small" }, M.t("jfa.redact"));
    open.addEventListener("click", () => {
      const reason = h("input", { id: "jfa-redact-" + target.replace(/\W/g, "-"), placeholder: M.t("jfa.redact.reason") });
      const status = M.statusLine();
      append(clear(box), h("label", { for: reason.id }, M.t("jfa.redact.reason")), reason,
        h("button", { type: "button", class: "small", onclick: async () => {
          if (!reason.value.trim()) { reason.focus(); return; }
          status.busy(M.t("jfa.redact.busy"));
          try { await M.api.post(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/redact", { target, reason: reason.value.trim() }); done(); }
          catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
        } }, M.t("jfa.redact.confirm")), status.el);
      reason.focus();
    });
    append(box, open);
    return box;
  }

  // ---- §20.3, §20.4: the answer ------------------------------------------

  async function answerPart(ctx, r, reload) {
    const path = ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/answers";
    const box = h("section", { class: "jfa-answer", "aria-labelledby": "jfa-answer-title" }, h("h3", { id: "jfa-answer-title" }, M.t("jfa.answer.title")));
    const status = M.statusLine();
    let mine = [];
    try { mine = (await M.api.get(path + "?mine=true")).items || []; } catch (err) { /* none yet, or not readable: the form */ }
    const own = mine.find((a) => !a.withdrawn);
    // After the window (§20.3, §20.8): the author reads a named answer at any time, and a human
    // author removes it; an anonymous one is no longer theirs to find, and nothing is shown.
    if (r.status !== "answering") {
      if (!own || own.anonymous) return null;
      append(box, h("p", { class: "muted" }, M.t("jfa.answer.yours_after")),
        own.redaction ? h("p", { class: "muted" }, M.t("jfa.redacted"))
          : [FIELDS.map(([k, label]) => own[k] ? [h("h4", null, label()), h("div", { class: "md" }, M.markdown(own[k]))] : null),
            ctx.me.kind === "human" ? redactButton(ctx, r, "answer:" + own.id, reload) : null]);
      return box;
    }
    if (own || mine.length) {
      append(box, h("p", { class: "muted" }, own ? (own.anonymous ? M.t("jfa.answer.yours_anonymous") : M.t("jfa.answer.yours")) : M.t("jfa.answer.withdrawn")),
        own ? FIELDS.map(([k, label]) => own[k] ? [h("h4", null, label()), h("div", { class: "md" }, M.markdown(own[k]))] : null) : null,
        own ? h("button", { type: "button", onclick: async () => {
          status.busy(M.t("jfa.answer.withdrawing"));
          try {
            await M.api.del(path + "/mine");
            if (own.anonymous) withdrawnHere.add(r.id);
            reload();
          } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
        } }, M.t("jfa.answer.withdraw")) : null, status.el);
      return box;
    }
    if (withdrawnHere.has(r.id)) {
      append(box, h("p", { class: "muted" }, M.t("jfa.answer.no_second")));
      return box;
    }
    const inputs = FIELDS.map(([k, label]) => {
      const id = "jfa-" + k;
      const area = h("textarea", { id, rows: "4" });
      return { k, area, nodes: [h("label", { for: id }, label()), area] };
    });
    const anonymous = h("input", { type: "checkbox", id: "jfa-anonymous" });
    // What anonymity does not cover, said before an anonymous answer is sent (§20.4).
    const limits = h("div", { class: "hint jfa-limits", id: "jfa-limits" }, h("p", null, M.t("jfa.limits.title")),
      h("ul", null, h("li", null, M.t("jfa.limits.wording")), h("li", null, M.t("jfa.limits.timing")), h("li", null, M.t("jfa.limits.copies")),
        h("li", null, M.t("jfa.limits.transport")), h("li", null, M.t("jfa.limits.small"))));
    limits.hidden = true;
    anonymous.addEventListener("change", () => { limits.hidden = !anonymous.checked; });
    const error = h("p", { class: "field-error", role: "alert" });
    append(box, h("p", { class: "hint" }, M.t("jfa.answer.hint")), h("form", {
      class: "jfa-answer-form",
      onsubmit: async (e) => {
        e.preventDefault();
        error.textContent = "";
        const body = { anonymous: anonymous.checked };
        inputs.forEach((x) => { const v = x.area.value.trim(); if (v) body[x.k] = v; });
        const texts = inputs.map((x) => body[x.k] || "");
        if (!texts.some(Boolean)) { error.textContent = M.t("jfa.refused.empty"); inputs[0].area.focus(); return; }
        if (texts.some((t) => bytes(t) > TEXT_MAX) || bytes(texts.join("")) > ALL_MAX) { error.textContent = M.t("jfa.refused.too_long"); return; }
        status.busy(M.t("jfa.answer.sending"));
        try { await M.api.post(path, body); reload(); } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
      },
    }, inputs.map((x) => x.nodes), h("p", { class: "check" }, anonymous, h("label", { for: "jfa-anonymous" }, " " + M.t("jfa.answer.anonymous"))), limits, error,
    h("button", { type: "submit" }, M.t("jfa.answer.send")), status.el));
    return box;
  }

  // ---- §20.3: the answers, for their readers -------------------------------

  async function answersPart(ctx, r, reload) {
    let items;
    try { items = (await M.api.get(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/answers")).items || []; } catch (err) { return { box: null, items: [] }; }
    const box = h("section", { class: "jfa-answers", "aria-labelledby": "jfa-answers-title" },
      h("h3", { id: "jfa-answers-title" }, M.t("jfa.answers.title")), h("p", { class: "hint" }, M.t("jfa.answers.hint")),
      items.length ? h("ol", { class: "jfa-answer-list" }, items.map((a) => h("li", { "data-answer": a.id },
        h("p", { class: "muted" }, a.anonymous ? M.t("jf.anonymous") : [M.t("jfa.answers.by"), " ", M.dom.memberRef(ctx, a.author)], a.withdrawn ? " · " + M.t("jfa.answer.withdrawn") : ""),
        a.redaction ? h("p", { class: "muted" }, M.t("jfa.redacted"))
          : [FIELDS.map(([k, label]) => a[k] ? [h("h4", null, label()), h("div", { class: "md" }, M.markdown(a[k]))] : null), redactButton(ctx, r, "answer:" + a.id, reload)])))
        : h("p", { class: "muted" }, M.t("jfa.answers.none")));
    return { box, items };
  }

  // ---- §20.5: the statement, by a human moderator ----------------------------

  function statementPart(ctx, r, answers, reload) {
    const named = [...new Set(answers.filter((a) => !a.anonymous && !a.withdrawn && a.author).map((a) => a.author))];
    const topics = [{ title: "", summary: "", items: [], proposals: [] }];
    const status = M.statusLine();
    const list = h("ol", { class: "jfa-topics" });
    const fromSelect = (item) => {
      const s = h("select", { "aria-label": M.t("jfa.statement.from") }, h("option", { value: "anonymous" }, M.t("jf.anonymous")),
        named.map((id) => h("option", { value: id }, "@" + (M.dom.handleOf(ctx, { id }) || id))));
      s.value = item.from;
      s.addEventListener("change", () => { item.from = s.value; });
      return s;
    };
    const bind = (obj, key, el) => { el.value = obj[key] || ""; el.addEventListener("input", () => { obj[key] = el.value; }); return el; };
    function draw() {
      append(clear(list), topics.map((t, i) => h("li", { class: "jfa-topic" },
        h("label", { for: "jfa-t" + i + "-title" }, M.t("jfa.statement.topic")), bind(t, "title", h("input", { id: "jfa-t" + i + "-title", maxlength: "200" })),
        h("label", { for: "jfa-t" + i + "-summary" }, M.t("jfa.statement.summary")), bind(t, "summary", h("textarea", { id: "jfa-t" + i + "-summary", rows: "3" })),
        h("h5", null, M.t("jfa.statement.items")),
        t.items.map((it, k) => h("div", { class: "inline-form" }, bind(it, "text", h("input", { "aria-label": M.t("jfa.statement.item"), id: "jfa-t" + i + "-i" + k })), fromSelect(it),
          h("button", { type: "button", class: "small", onclick: () => { t.items.splice(k, 1); draw(); } }, M.t("jfa.remove")))),
        h("button", { type: "button", class: "small", onclick: () => { t.items.push({ text: "", from: "anonymous" }); draw(); } }, M.t("jfa.statement.add_item")),
        h("h5", null, M.t("jf.proposals")),
        t.proposals.map((p, k) => h("div", { class: "inline-form" }, bind(p, "title", h("input", { "aria-label": M.t("jfa.proposal.title"), id: "jfa-t" + i + "-s" + k })),
          bind(p, "reason", h("input", { "aria-label": M.t("jfa.proposal.reason"), id: "jfa-t" + i + "-s" + k + "-reason" })),
          h("button", { type: "button", class: "small", onclick: () => { t.proposals.splice(k, 1); draw(); } }, M.t("jfa.remove")))),
        h("button", { type: "button", class: "small", disabled: t.proposals.length >= 5 ? true : null, onclick: () => { t.proposals.push({ title: "", reason: "" }); draw(); } }, M.t("jfa.statement.add_proposal")),
        topics.length > 1 ? h("button", { type: "button", class: "small", onclick: () => { topics.splice(i, 1); draw(); } }, M.t("jfa.statement.remove_topic")) : null)));
    }
    draw();
    return h("section", { class: "jfa-statement", "aria-labelledby": "jfa-statement-title" },
      h("h3", { id: "jfa-statement-title" }, M.t("jfa.statement.title")), h("p", { class: "hint" }, M.t("jfa.statement.hint")),
      h("form", { onsubmit: async (e) => {
        e.preventDefault();
        const body = { topics: topics.filter((t) => t.title.trim()).map((t) => ({ title: t.title.trim(), summary: t.summary.trim() || undefined,
          items: t.items.filter((it) => it.text.trim()).map((it) => ({ text: it.text.trim(), from: it.from })),
          proposals: t.proposals.filter((p) => p.title.trim()).map((p) => ({ title: p.title.trim(), reason: p.reason.trim() || undefined })) })) };
        if (!body.topics.length) { list.querySelector("input").focus(); return; }
        status.busy(M.t("jfa.statement.sending"));
        try { await M.api.post(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/statement", body); reload(); } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
      } }, list, h("button", { type: "button", class: "small", onclick: () => { topics.push({ title: "", summary: "", items: [], proposals: [] }); draw(); } }, M.t("jfa.statement.add_topic")),
      h("div", { class: "actions" }, h("button", { type: "submit" }, M.t("jfa.statement.send"))), status.el));
  }

  // ---- §20.5: a post in the open step ----------------------------------------

  function postsPart(ctx, r, step, reload) {
    const topics = (r.statement && r.statement.topics) || [];
    const mineHere = (t) => (r.posts || []).some((p) => p.by === ctx.me.id && p.topic_id === t.id && p.step === step.kind);
    const others = (r.participants || []).filter((p) => p.member_id !== ctx.me.id);
    const repliable = (t) => (r.posts || []).filter((p) => p.topic_id === t.id && p.step === "response" && (p.to || []).includes(ctx.me.id));
    // A step's topics (a further step may name some); a reply only where a response addressed me,
    // a rejoinder only where my response received a reply (§20.5).
    const mine = (t) => (r.posts || []).filter((p) => p.topic_id === t.id && p.step === "response" && p.by === ctx.me.id).map((p) => p.id);
    const replied = (t) => (r.posts || []).some((p) => p.topic_id === t.id && p.step === "reply" && (p.in_reply_to || []).some((id) => mine(t).includes(id)));
    const postable = (t) => (!Array.isArray(step.topics) || step.topics.includes(t.id))
      && (step.kind !== "reply" || repliable(t).length > 0) && (step.kind !== "rejoinder" || replied(t));
    return h("section", { class: "jfa-posts", "aria-labelledby": "jfa-posts-title" },
      h("h3", { id: "jfa-posts-title" }, M.t("jfa.posts.title")), h("p", { class: "hint" }, M.t("jfa.posts.hint")),
      topics.filter((t) => !t.redaction && postable(t)).map((t) => {
        if (mineHere(t)) return h("p", { class: "muted" }, M.t("jfa.posts.done", { topic: t.title }));
        const id = "jfa-post-" + t.id.replace(/\W/g, "-");
        const body = h("textarea", { id, rows: "3" });
        const status = M.statusLine();
        const toBoxes = ["response", "further"].includes(step.kind) ? others.map((p) => {
          const box = h("input", { type: "checkbox", id: id + "-to-" + p.member_id });
          return [box, p.member_id, h("label", { class: "check", for: box.id }, box, " ", M.dom.memberRef(ctx, p.member_id))];
        }) : [];
        const replyTo = step.kind === "reply" ? repliable(t) : [];
        return h("form", { class: "jfa-post-form", "data-topic": t.id, onsubmit: async (e) => {
          e.preventDefault();
          if (!body.value.trim()) { body.focus(); return; }
          const sent = { step: step.kind, topic_id: t.id, body: body.value.trim() };
          const to = toBoxes.filter((x) => x[0].checked).map((x) => x[1]);
          if (to.length) sent.to = to;
          if (replyTo.length) sent.in_reply_to = replyTo.map((p) => p.id);
          status.busy(M.t("jfa.posts.sending"));
          try { await M.api.post(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/posts", sent); reload(); } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
        } }, h("label", { for: id }, t.title), body,
        toBoxes.length ? h("fieldset", null, h("legend", null, M.t("jfa.posts.to")), toBoxes.map((x) => x[2])) : null,
        h("button", { type: "submit" }, M.t("jfa.posts.send")), status.el);
      }));
  }

  // ---- §20.5: a further step, by the moderator --------------------------------

  function stepPart(ctx, r, reload) {
    const reason = h("input", { id: "jfa-step-reason" });
    const status = M.statusLine();
    return h("form", { class: "inline-form jfa-step", onsubmit: async (e) => {
      e.preventDefault();
      if (!reason.value.trim()) { reason.focus(); return; }
      status.busy(M.t("jfa.step.sending"));
      try { await M.api.post(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/steps", { reason: reason.value.trim() }); reload(); } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
    } }, h("label", { for: "jfa-step-reason" }, M.t("jfa.step.reason")), reason, h("button", { type: "submit" }, M.t("jfa.step.add")), h("p", { class: "hint" }, M.t("jfa.step.hint")), status.el);
  }

  // ---- §20.6: the report and its triage, by a human moderator -----------------

  function reportPart(ctx, r, reload) {
    const topics = (r.statement && r.statement.topics) || [];
    const fromStatement = topics.flatMap((t) => (t.proposals || []).filter((p) => !p.redaction).map((p) => ({ topic: t, p })));
    // A decision rests on a rules version the project names (§20.6); without one, nothing is decided here.
    const decides = adminTeam(ctx) && Number.isInteger(ctx.project.rules_version) && ctx.project.rules_version >= 1;
    const summary = h("textarea", { id: "jfa-report-summary", rows: "4" });
    const findings = h("textarea", { id: "jfa-report-findings", rows: "4", "aria-describedby": "jfa-report-findings-hint" });
    const rows = fromStatement.map(({ topic, p }) => {
      const id = "jfa-triage-" + p.id.replace(/\W/g, "-");
      const triage = h("select", { id }, h("option", { value: "to_owner" }, M.t("jf.triage.to_owner")),
        decides ? h("option", { value: "adopt" }, M.t("jfa.triage.adopt")) : null, decides ? h("option", { value: "reject" }, M.t("jfa.triage.reject")) : null,
        h("option", { value: "drop" }, M.t("jfa.triage.drop")));
      const why = h("input", { id: id + "-reason", "aria-label": M.t("jfa.triage.reason") });
      return { topic, p, triage, why, nodes: h("div", { class: "jfa-triage" }, h("label", { for: id }, p.title), triage, why) };
    });
    const status = M.statusLine();
    return h("section", { class: "jfa-report-form", "aria-labelledby": "jfa-report-form-title" },
      h("h3", { id: "jfa-report-form-title" }, M.t("jfa.report.title")), h("p", { class: "hint" }, M.t("jfa.report.hint")),
      h("form", { onsubmit: async (e) => {
        e.preventDefault();
        const body = { findings: findings.value.split("\n").map((l) => l.trim()).filter(Boolean).map((text) => ({ text })), proposals: [] };
        if (summary.value.trim()) body.summary = summary.value.trim();
        // A human decides on the rules and their own preferences, by version (§20.6, §19.4); 0 is none written.
        let basis = null;
        if (rows.some((x) => ["adopt", "reject"].includes(x.triage.value))) {
          const prefs = await M.api.get("/me/preferences").catch(() => null);
          basis = { rules_version: ctx.project.rules_version, human_id: ctx.me.id, preferences_version: (prefs && prefs.version) || 0 };
        }
        for (const x of rows) {
          if (x.triage.value === "drop") continue;
          const one = { title: x.p.title, reason: x.p.reason || undefined, topic_id: x.topic.id, statement_proposal_id: x.p.id };
          if (x.triage.value === "to_owner") one.triage = "to_owner";
          else {
            if (!x.why.value.trim()) { x.why.focus(); return; }
            Object.assign(one, { triage: "decided", decision: { outcome: x.triage.value, reason: x.why.value.trim(), basis } });
          }
          body.proposals.push(one);
        }
        status.busy(M.t("jfa.report.sending"));
        try { await M.api.post(ctx.base + "/jour-fixe/rounds/" + encodeURIComponent(r.id) + "/report", body); reload(); } catch (err) { status.fail(M.t("jfa.failed"), said(err)); }
      } }, h("label", { for: "jfa-report-summary" }, M.t("jfa.report.summary")), summary,
      h("label", { for: "jfa-report-findings" }, M.t("jfa.report.findings")), findings, h("p", { class: "hint", id: "jfa-report-findings-hint" }, M.t("jfa.report.findings_hint")),
      rows.length ? [h("h4", null, M.t("jfa.report.triage")), rows.map((x) => x.nodes)] : null,
      h("div", { class: "actions" }, h("button", { type: "submit" }, M.t("jfa.report.send"))), status.el));
  }

  // ---- §20.8: the report's texts, redacted ------------------------------------

  function reportRedactions(ctx, r, reload) {
    const rep = r.report;
    const may = adminTeam(ctx) || (ctx.me.kind === "human" && ids(r.invited).includes(ctx.me.id));
    if (!rep || !may) return null;
    const line = (label, target, gone) => (gone ? null : h("li", null, label, " ", redactButton(ctx, r, target, reload)));
    return h("details", { class: "jfa-report-redact" }, h("summary", null, M.t("jfa.report.redact_title")),
      h("ul", null, rep.summary ? line(M.t("jf.report"), "summary", rep.summary_redaction) : null,
        (rep.findings || []).map((f) => line(f.text, "finding:" + f.id, f.redaction)),
        (rep.proposals || []).map((p) => line(p.title, "proposal:" + p.id, p.redaction))));
  }

  // Everything this reader may do in this round, in the order of the round.
  async function parts(ctx, r, reload) {
    const me = ctx.me.id;
    const moderator = r.moderator && r.moderator.member_id === me;
    const participant = ids(r.participants).includes(me);
    const out = [];
    // One's own answer: given while the window is open, read (and, named, removed) afterwards.
    const readers0 = moderator || adminTeam(ctx);
    if (participant && (r.status === "answering" || !readers0)) out.push(await answerPart(ctx, r, reload));
    const readers = moderator || adminTeam(ctx);
    const read = readers ? await answersPart(ctx, r, reload) : { box: null, items: [] };
    if (read.box) out.push(read.box);
    if (moderator && ctx.me.kind === "human" && r.status === "statement" && !r.statement) out.push(statementPart(ctx, r, read.items, reload));
    const open = (r.steps || []).find((s) => s.opened_at && !s.closed_at && s.kind !== "statement");
    if (r.status === "exchange" && open && (open.eligible || []).includes(me)) out.push(postsPart(ctx, r, open, reload));
    if (moderator && ctx.me.kind === "human" && r.status === "exchange") out.push(stepPart(ctx, r, reload));
    if (moderator && ctx.me.kind === "human" && r.status === "reporting") out.push(reportPart(ctx, r, reload));
    out.push(reportRedactions(ctx, r, reload));
    return out.filter(Boolean);
  }

  M.jourFixeAct = { parts };
})(window.Maity);
