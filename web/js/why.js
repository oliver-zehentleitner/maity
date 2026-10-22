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
  const STATUS_LABELS = {
    "needs-review": "needs review", "pending-confirmation": "pending confirmation", open: "open",
    active: "active", superseded: "superseded", other: "other",
  };

  // A member's failure (§11.3), in words.
  const REASONS = {
    forge_unavailable: "its .keep-the-why could not be read from the forge",
    config_missing: "there is no .keep-the-why at its path",
    no_state_url: "its .keep-the-why names no dashboard-state",
    location_not_followed: "its location is not a directory in this repository, so the hub does not follow it",
    state_url_invalid: "its dashboard-state URL is not a plain https URL",
    address_refused: "its dashboard-state points at an address the hub does not read from",
    redirect_refused: "its dashboard-state answered with a redirect, which the hub does not follow",
    timeout: "its state.json did not answer in time",
    http_status: "its state.json answered with an error status",
    too_large: "its state.json is larger than 1 MiB",
    not_json: "its state.json is not JSON",
    state_json_version: "its state.json is in a version the hub does not know",
    shape: "its state.json does not have the expected shape",
  };

  // The root's own read failed (ktw_unavailable on the call): said of the root.
  const ROOT_REASONS = {
    forge_unavailable: "the forge did not give the hub the repository's root .keep-the-why",
  };

  const memberName = (m) => (m.path === "" ? "the project root" : (m.name || m.path));

  function reasonText(err) {
    if (!err) return "";
    const base = REASONS[err.reason] || err.reason || err.code;
    if (err.reason === "http_status" && err.status) return base + " (" + err.status + ")";
    if (err.reason === "state_json_version" && err.version) return base + " (" + err.version + ")";
    return base;
  }

  const link = (url, text) => (safeUrl(url) ? h("a", { href: safeUrl(url), rel: "noopener noreferrer" }, text) : text);

  // An entry's link is used only where it points into its own part's
  // published dashboard (the hub builds it as dashboard_url + "#entry/…").
  const entryLink = (a, member, text) => (member && typeof a.link === "string" && safeUrl(member.dashboard_url)
    && a.link.startsWith(member.dashboard_url + "#entry/") ? link(a.link, text) : text);

  function counts(summary) {
    if (!summary) return h("span", { class: "muted" }, "no read yet");
    const parts = STATUSES.filter((s) => summary.status && summary.status[s])
      .map((s) => summary.status[s] + " " + STATUS_LABELS[s]);
    return h("span", null, summary.entries + " entr" + (summary.entries === 1 ? "y" : "ies")
      + (parts.length ? " (" + parts.join(", ") + ")" : ""));
  }

  // Each count is null when that export does not carry it: said per field.
  function findings(summary) {
    const f = summary && summary.findings;
    if (!f || (f.errors === null && f.warnings === null)) return "—";
    const n = (v) => (v === null || v === undefined ? "—" : String(v));
    return n(f.errors) + " errors, " + n(f.warnings) + " warnings";
  }

  function summaryBox(answer) {
    const s = answer.summary;
    return h("div", { class: "why-summary" },
      h("p", { class: "why-headline" },
        s.attention
          ? h("strong", null, s.attention + (s.attention === 1 ? " entry needs" : " entries need") + " attention")
          : h("strong", null, "Nothing needs attention"),
        " · " + s.entries + " entries in " + s.members + " part" + (s.members === 1 ? "" : "s") + " of the project",
        s.failed ? h("span", { class: "flag-inline" }, " · " + s.failed + " could not be read") : null),
      h("p", { class: "muted" }, "Linter: " + findings(s) + ". Read by the hub " + formatAgo(answer.observed_at)
        + (answer.fresh === false ? " (from its cache)" : "") + "."),
      answer.family_truncated ? h("p", { class: "flag" }, "The family is larger than the hub reads (depth 4, 32 parts); the rest is not shown.") : null,
      answer.skipped ? h("p", { class: "muted" }, answer.skipped + " entries without an id were skipped.") : null);
  }

  function membersTable(answer) {
    return h("table", { class: "why-members", tabindex: "0", "aria-label": "Parts of the project" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, "Part"), h("th", { scope: "col" }, "Entries"),
        h("th", { scope: "col" }, "Attention"), h("th", { scope: "col" }, "Linter"),
        h("th", { scope: "col" }, "Exported"))),
      h("tbody", null, answer.members.map((m) => h("tr", { class: m.error ? "failed" : "" },
        h("td", null, link(m.dashboard_url, memberName(m)), m.path ? h("span", { class: "muted" }, " · " + m.path + "/") : null,
          m.error ? h("p", { class: "flag" }, "Could not be read: " + reasonText(m.error)
            + (m.summary ? ". Shown is its last good read." : ".")) : null),
        h("td", null, counts(m.summary)),
        h("td", null, m.summary ? String(m.summary.attention) : "—"),
        h("td", null, findings(m.summary)),
        h("td", null, m.summary && m.summary.generated ? h("span", { title: formatTime(m.summary.generated) }, formatAgo(m.summary.generated)) : "—")))));
  }

  function attentionList(answer) {
    const byMember = {};
    answer.attention.forEach((a) => { (byMember[a.member] = byMember[a.member] || []).push(a); });
    const groups = answer.members.filter((m) => byMember[m.path]);
    if (!groups.length) {
      return h("p", { class: "muted" }, "No entry is open, needs review or waits for confirmation.");
    }
    return [groups.map((m) => h("section", { class: "why-group", "aria-label": memberName(m) },
      h("h3", null, memberName(m)[0].toUpperCase() + memberName(m).slice(1)),
      h("ul", { class: "why-entries" }, byMember[m.path].map((a) => h("li", null,
        h("span", { class: "badge why-" + a.status }, STATUS_LABELS[a.status] || a.status),
        " ", entryLink(a, m, a.title),
        h("span", { class: "muted" }, " · " + [a.topic || a.file, (a.type || []).join(", ")].filter(Boolean).join(" · "))))))),
    answer.truncated ? h("p", { class: "muted" }, "Only the first 200 are listed.") : null];
  }

  // The view's title row: Read again is there in every state, and off while a read runs.
  function toolbar(root, ctx) {
    const again = h("button", { type: "button", class: "small", onclick: () => { again.disabled = true; load(root, ctx, true); } }, "Read again");
    return h("div", { class: "toolbar" }, h("h2", null, "Why"), again);
  }

  function render(root, answer, ctx, note) {
    clear(root);
    append(root,
      toolbar(root, ctx),
      h("p", { class: "muted" }, "The project's decisions and their reasons, as its published Keep the Why dashboard shows them. "
        + "The hub reads them from the repository; nothing here changes them."),
      note || null,
      summaryBox(answer),
      h("h3", null, "Needs attention"),
      attentionList(answer),
      h("h3", null, "Parts"),
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
          h("p", null, "This project publishes no Keep the Why dashboard yet."),
          h("p", { class: "muted" }, ctx.project.repository
            ? "The hub reads the dashboard-state line of the repository's root .keep-the-why, and that line is missing (or the file is)."
            : "It needs a repository first: the hub reads the dashboard-state line of the repository's root .keep-the-why.")));
        return;
      }
      if (err.code === "ktw_unavailable") {
        const last = err.details && err.details.last;
        const why = err.details && err.details.reason;
        const note = h("p", { class: "flag" }, "The hub could not read the project's root .keep-the-why just now ("
          + (ROOT_REASONS[why] || REASONS[why] || why || "unavailable") + ")."
          + (last ? " Shown is its last good read, from " + formatAgo(last.observed_at) + "." : ""));
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
