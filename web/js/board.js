// (2) The board: cards by status, with claim holder, lease and
// dependencies. Releases are a card kind with their pull requests as the
// hub observed them; readiness and its reasons come from the hub and are
// shown, never computed here (docs/api.md §6.7).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, safeUrl, formatAgo, formatTime } = M.dom;

  const COLUMNS = [
    ["proposed", "Proposed"],
    ["open", "Open"],
    ["in_progress", "In progress"],
    ["blocked", "Blocked"],
    ["review", "Review"],
    ["done", "Done"],
    ["cancelled", "Cancelled"],
  ];

  // Closed cards older than this are left out (closed_after).
  const CLOSED_WINDOW_DAYS = 14;

  const KIND_LABELS = { release: "Release", contract: "Contract", maintenance_round: "Context round" };

  const status = (s) => s.replace("_", " ");

  function blockingText(b) {
    switch (b.reason) {
      case "probe_not_configured": return "no forge probe for this project";
      case "task_open": return b.task + " is not done";
      case "pr_open": return "#" + b.pr + " is not merged";
      case "pr_unverified": return "#" + b.pr + " is not observed yet";
      case "pr_mismatch": return "#" + b.pr + " head differs from the report";
      case "group_incomplete": return "group " + b.tasks.join(" + ") + " is incomplete";
      case "checklist_open": return "checklist item " + b.item + " is open";
      default: return b.reason;
    }
  }

  function claimLine(ctx, c) {
    const claim = c.claim;
    if (!claim) {
      return h("p", { class: "claim unclaimed" },
        c.assigned_to ? "Assigned to " + ctx.nameOf(c.assigned_to) + ", not claimed" : "Unclaimed");
    }
    return h("p", { class: "claim" },
      "Claimed by ", h("strong", null, ctx.nameOf(claim.holder)), " · " + formatAgo(claim.since),
      claim.expired
        ? h("span", { class: "expired" }, " · lease expired " + formatTime(claim.lease_until))
        : (claim.lease_until ? h("span", { class: "lease" }, " · lease until " + formatTime(claim.lease_until)) : null));
  }

  function edges(label, ids, byId) {
    if (!ids || !ids.length) return null;
    return h("div", { class: "deps" },
      h("span", { class: "label" }, label),
      h("ul", null, ids.map((id) => {
        const dep = byId[id];
        const closed = dep && (dep.status === "done" || dep.status === "cancelled");
        return h("li", { class: dep ? (closed ? "met" : "unmet") : "" },
          id + (dep ? " — " + dep.title + " (" + status(dep.status) + ")" : ""));
      })));
  }

  function checkpoint(c) {
    const cp = c.checkpoint;
    if (!cp) return null;
    return h("div", { class: "checkpoint" },
      h("span", { class: "label" }, "Checkpoint " + formatAgo(cp.updated_at) + " (" + cp.verification + ")"),
      h("p", { class: "pre" }, "Done: " + cp.last_step + "\nNext: " + cp.next_step),
      cp.branch ? h("p", { class: "muted" }, cp.branch + (cp.head ? " @ " + cp.head : "")) : null);
  }

  function report(c) {
    const r = c.report;
    if (!r) return null;
    const pr = r.pr ? "PR #" + r.pr.number : (r.pr_status === "none" ? "no PR" : "PR unknown: " + (r.pr_unknown_reason || "—"));
    const observed = r.observed
      ? "observed " + r.observed.pr_state + ", checks " + r.observed.checks + " · " + formatAgo(r.observed.observed_at)
      : "not observed by the hub";
    return h("div", { class: "report" + (r.mismatch ? " mismatch" : "") },
      h("span", { class: "label" }, "Report " + formatAgo(r.reported_at) + " (" + r.verification + ")"),
      h("p", { class: "pre" }, r.summary),
      h("p", { class: "muted" }, pr + " · " + observed),
      r.mismatch ? h("p", { class: "flag" }, "The observed head differs from the reported one.") : null);
  }

  function pullRequests(rel) {
    const prs = rel.pull_requests || [];
    if (!prs.length) return h("p", { class: "muted" }, "No pull requests yet.");
    return h("table", { class: "prs" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, "PR"), h("th", { scope: "col" }, "State"),
        h("th", { scope: "col" }, "Checks"), h("th", { scope: "col" }, "Observed"))),
      h("tbody", null, prs.map((pr) => h("tr", null,
        h("td", null, safeUrl(pr.url) ? h("a", { href: safeUrl(pr.url), rel: "noopener noreferrer" }, "#" + pr.number) : "#" + pr.number,
          " " + (pr.title || ""), h("span", { class: "muted" }, " · " + pr.source + (pr.task_id ? " by " + pr.task_id : ""))),
        h("td", { class: "pr-" + pr.state }, pr.state),
        h("td", { class: "checks-" + pr.checks }, pr.checks || "—"),
        h("td", null, pr.observed_at ? formatAgo(pr.observed_at) + (pr.head_sha ? " @ " + pr.head_sha : "") : "not observed")))));
  }

  function release(rel) {
    const r = rel.readiness || { ready: false, blocking: [] };
    return [
      pullRequests(rel),
      rel.checklist && rel.checklist.length
        ? h("ul", { class: "checklist" }, rel.checklist.map((item) =>
          h("li", { class: item.done ? "met" : "unmet" }, (item.done ? "✓ " : "○ ") + item.text)))
        : null,
      r.ready
        ? h("div", { class: "readiness ready" }, h("strong", null, "Ready to tag"))
        : h("div", { class: "readiness not-ready" }, h("strong", null, "Not ready: "),
          r.blocking.map(blockingText).join("; ")),
      rel.tag ? h("p", { class: "muted" }, "Tag " + rel.tag.name + ": " + (rel.tag.found ? "found" : "not found")) : null,
    ];
  }

  function card(ctx, c, byId) {
    return h("article", { class: "card card-" + c.kind, "aria-label": c.title },
      h("header", null,
        h("span", { class: "card-id" }, c.id),
        KIND_LABELS[c.kind]
          ? h("span", { class: "badge " + c.kind }, KIND_LABELS[c.kind] + (c.kind === "release" ? " " + c.release.version : ""))
          : null,
        c.label ? h("span", { class: "label-tag" }, c.label) : null,
        c.area ? h("span", { class: "area" }, c.area) : null),
      h("h3", null, c.title),
      claimLine(ctx, c),
      edges("Depends on", c.depends_on, byId),
      edges("Ships with", c.ships_with, byId),
      c.blocked_by_request
        ? h("p", { class: "flag" }, "Waits for ", h("a", { href: ctx.link("inbox") }, "an answer"), " (",
          h("span", { class: "request-id" }, c.blocked_by_request), ")")
        : null,
      c.contract
        ? h("p", { class: "muted" }, "Contract " + c.contract.state + ", arbiter " + ctx.nameOf(c.contract.arbiter))
        : null,
      checkpoint(c),
      report(c),
      c.kind === "release" ? release(c.release) : null);
  }

  M.views.board = async function (ctx, root) {
    const since = new Date(Date.now() - CLOSED_WINDOW_DAYS * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const tasks = await M.api.getAll(ctx.base + "/tasks?status=all&closed_after=" + encodeURIComponent(since));
    const byId = {};
    tasks.items.forEach((t) => { byId[t.id] = t; });
    const known = new Set(COLUMNS.map(([s]) => s));
    const other = tasks.items.filter((t) => !known.has(t.status));

    append(root, h("h2", null, "Board"),
      h("p", { class: "muted" }, "Every open card, and the done and cancelled ones of the last " + CLOSED_WINDOW_DAYS + " days."),
      tasks.items.length
        ? null
        : h("p", { class: "first-hint" }, "No cards yet. Your agents put the work here: they propose cards in their "
          + "areas, claim them and report when they are done. Ask an agent in its chat to propose what it will work on."),
      h("div", { class: "columns" },
        COLUMNS.map(([s, label]) => {
          const cards = tasks.items.filter((t) => t.status === s);
          return h("section", { class: "column", "aria-label": label },
            h("h3", { class: "column-head" }, label, h("span", { class: "count" }, String(cards.length))),
            cards.length ? cards.map((c) => card(ctx, c, byId)) : h("p", { class: "muted" }, "—"));
        }),
        other.length
          ? h("section", { class: "column", "aria-label": "Other" },
            h("h3", { class: "column-head" }, "Unknown status"),
            other.map((c) => card(ctx, c, byId)))
          : null));
  };
})(window.Maity);
