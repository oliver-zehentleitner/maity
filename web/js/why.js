// (7) Why: the project's published Keep the Why dashboard state as the hub
// read it (docs/api.md §11.3) — the family's summary, one row per member,
// and the entries that need attention, grouped by member, each linking to
// its entry in the published dashboard. Read-only: the hub never reads or
// writes context/, and neither does this view. Every string from an export
// is data and rendered as text; links are used only when plain https.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatAgo, formatTime } = M.dom;

  const STATUSES = ["needs-review", "pending-confirmation", "open", "active", "superseded", "other"];
  const STATUS_WORDS = {
    "needs-review": () => M.t("why.status.needs_review"), "pending-confirmation": () => M.t("why.status.pending_confirmation"),
    open: () => M.t("why.status.open"), active: () => M.t("why.status.active"),
    superseded: () => M.t("why.status.superseded"), other: () => M.t("why.status.other"),
  };
  const statusWord = (s) => (Object.hasOwn(STATUS_WORDS, s) ? STATUS_WORDS[s]() : s);

  // A member's failure (§11.3), in words.
  const REASONS = {
    forge_unavailable: () => M.t("why.reason.forge_unavailable"),
    config_missing: () => M.t("why.reason.config_missing"),
    no_state_url: () => M.t("why.reason.no_state_url"),
    location_not_followed: () => M.t("why.reason.location_not_followed"),
    state_url_invalid: () => M.t("why.reason.state_url_invalid"),
    address_refused: () => M.t("why.reason.address_refused"),
    redirect_refused: () => M.t("why.reason.redirect_refused"),
    timeout: () => M.t("why.reason.timeout"),
    http_status: () => M.t("why.reason.http_status"),
    too_large: () => M.t("why.reason.too_large"),
    not_json: () => M.t("why.reason.not_json"),
    state_json_version: () => M.t("why.reason.state_json_version"),
    shape: () => M.t("why.reason.shape"),
  };

  // The root's own read failed (ktw_unavailable on the call): said of the root.
  const ROOT_REASONS = {
    forge_unavailable: () => M.t("why.reason.root_forge_unavailable"),
  };

  const reasonWord = (table, reason) => (Object.hasOwn(table, reason) ? table[reason]() : null);

  const memberName = (m) => (m.path === "" ? M.t("why.root") : (m.name || m.path));

  function reasonText(err) {
    if (!err) return "";
    const base = reasonWord(REASONS, err.reason) || err.reason || err.code;
    if (err.reason === "http_status" && err.status) return M.t("why.reason.detail", { reason: base, detail: String(err.status) });
    if (err.reason === "state_json_version" && err.version) return M.t("why.reason.detail", { reason: base, detail: String(err.version) });
    return base;
  }

  const link = (url, text) => (safeUrl(url) ? h("a", { href: safeUrl(url), rel: "noopener noreferrer" }, text) : text);

  // An entry's link is used only where it points into its own part's
  // published dashboard (the hub builds it as dashboard_url + "#entry/…").
  const entryLink = (a, member, text) => (member && typeof a.link === "string" && safeUrl(member.dashboard_url)
    && a.link.startsWith(member.dashboard_url + "#entry/") ? link(a.link, text) : text);

  function counts(summary) {
    if (!summary) return h("span", { class: "muted" }, M.t("why.no_read"));
    const parts = STATUSES.filter((s) => summary.status && summary.status[s])
      .map((s) => M.t("why.count.status", { count: summary.status[s], status: statusWord(s) }));
    const entries = M.t("why.count.entries", { count: summary.entries });
    return h("span", null, parts.length ? M.t("why.count.with_statuses", { entries, statuses: M.fmt.list(parts) }) : entries);
  }

  // Each count is null when that export does not carry it: said per field.
  function findings(summary) {
    const f = summary && summary.findings;
    if (!f || (f.errors === null && f.warnings === null)) return "—";
    // Each count with its own plural form; a missing one has none.
    const errors = typeof f.errors === "number" ? M.t("why.findings.errors", { count: f.errors }) : M.t("why.findings.errors_unknown");
    const warnings = typeof f.warnings === "number" ? M.t("why.findings.warnings", { count: f.warnings }) : M.t("why.findings.warnings_unknown");
    return M.t("why.findings", { errors, warnings });
  }

  function summaryBox(answer) {
    const s = answer.summary;
    return h("div", { class: "why-summary" },
      h("p", { class: "why-headline" },
        s.attention
          ? h("strong", null, M.t("why.summary.attention", { count: s.attention }))
          : h("strong", null, M.t("why.summary.nothing")),
        " · " + M.t("why.summary.entries", { count: s.members, entries: M.t("why.count.entries", { count: s.entries }) }),
        s.failed ? h("span", { class: "flag-inline" }, " · " + M.t("why.summary.failed", { count: s.failed })) : null),
      h("p", { class: "muted" }, answer.fresh === false
        ? M.t("why.summary.read_cached", { findings: findings(s), ago: formatAgo(answer.observed_at) })
        : M.t("why.summary.read", { findings: findings(s), ago: formatAgo(answer.observed_at) })),
      answer.family_truncated ? h("p", { class: "flag" }, M.t("why.summary.family_truncated", { depth: 4, parts: 32 })) : null,
      answer.skipped ? h("p", { class: "muted" }, M.t("why.summary.skipped", { count: answer.skipped })) : null);
  }

  function membersTable(answer) {
    return h("table", { class: "why-members", tabindex: "0", "aria-label": M.t("why.parts.label") },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, M.t("why.parts.part")), h("th", { scope: "col" }, M.t("why.parts.entries")),
        h("th", { scope: "col" }, M.t("why.parts.attention")), h("th", { scope: "col" }, M.t("why.parts.linter")),
        h("th", { scope: "col" }, M.t("why.parts.exported")))),
      h("tbody", null, answer.members.map((m) => h("tr", { class: m.error ? "failed" : "" },
        h("td", null, link(m.dashboard_url, memberName(m)), m.path ? h("span", { class: "muted" }, " · " + m.path + "/") : null,
          m.error ? h("p", { class: "flag" }, (m.summary
            ? M.t("why.parts.failed_last", { reason: reasonText(m.error) }) : M.t("why.parts.failed", { reason: reasonText(m.error) }))) : null),
        h("td", null, counts(m.summary)),
        h("td", null, m.summary ? M.fmt.number(m.summary.attention) : "—"),
        h("td", null, findings(m.summary)),
        h("td", null, m.summary && m.summary.generated ? h("span", { title: formatTime(m.summary.generated) }, formatAgo(m.summary.generated)) : "—")))));
  }

  function attentionList(answer) {
    const byMember = {};
    answer.attention.forEach((a) => { (byMember[a.member] = byMember[a.member] || []).push(a); });
    const groups = answer.members.filter((m) => byMember[m.path]);
    if (!groups.length) {
      return h("p", { class: "muted" }, M.t("why.attention.none"));
    }
    return [groups.map((m) => h("section", { class: "why-group", "aria-label": memberName(m) },
      h("h3", null, m.path === "" ? M.t("why.root.heading") : memberName(m)),
      h("ul", { class: "why-entries" }, byMember[m.path].map((a) => h("li", null,
        h("span", { class: "badge why-" + a.status }, statusWord(a.status)),
        " ", entryLink(a, m, a.title),
        h("span", { class: "muted" }, " · " + [a.topic || a.file, M.fmt.list(a.type || [])].filter(Boolean).join(" · "))))))),
    answer.truncated ? h("p", { class: "muted" }, M.t("why.attention.truncated", { count: 200 })) : null];
  }

  // The view's title row: Read again is there in every state, and off while a read runs.
  function toolbar(root, ctx) {
    const again = h("button", { type: "button", class: "small", onclick: () => { again.disabled = true; load(root, ctx, true); } }, M.t("why.read_again"));
    return h("div", { class: "toolbar" }, h("h2", null, M.t("why.title")), again);
  }

  function render(root, answer, ctx, note) {
    clear(root);
    append(root,
      toolbar(root, ctx),
      h("p", { class: "muted" }, M.t("why.intro")),
      note || null,
      summaryBox(answer),
      h("h3", null, M.t("why.attention.title")),
      attentionList(answer),
      h("h3", null, M.t("why.parts.title")),
      membersTable(answer));
  }

  async function load(root, ctx, fresh) {
    try {
      const answer = await M.api.get(ctx.base + "/keep-the-why" + (fresh ? "?max_age=0" : ""));
      render(root, answer, ctx);
    } catch (err) {
      clear(root);
      if (err.code === "ktw_not_configured") {
        append(root, toolbar(root, ctx), h("div", { class: "empty-state why-empty" },
          h("p", null, M.t("why.empty")),
          h("p", { class: "muted" }, ctx.project.repository ? M.t("why.empty.no_line") : M.t("why.empty.no_repository"))));
        return;
      }
      if (err.code === "ktw_unavailable") {
        const last = err.details && err.details.last;
        const why = err.details && err.details.reason;
        const reason = reasonWord(ROOT_REASONS, why) || reasonWord(REASONS, why) || why || M.t("why.reason.unavailable");
        const note = h("p", { class: "flag" }, last
          ? M.t("why.root_unreadable_last", { reason, ago: formatAgo(last.observed_at) })
          : M.t("why.root_unreadable", { reason }));
        if (last) { render(root, last, ctx, note); return; }
        append(root, toolbar(root, ctx), note);
        return;
      }
      append(root, toolbar(root, ctx), M.errorBox(err));
    }
  }

  M.views.why = async function (ctx, root) {
    await load(root, ctx, false);
  };
})(window.Maity);
