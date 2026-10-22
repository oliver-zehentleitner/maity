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

  // The hub's reasons (docs/api.md §6.7), in words; any other reason is
  // shown as it comes, with its details.
  function blockingText(b, byId) {
    const card = (id) => id + (byId[id] ? " (" + byId[id].title + ")" : "");
    switch (b.reason) {
      case "probe_not_configured": return "the hub observes nothing for this project (no forge probe)";
      case "task_open": return card(b.task) + " is not done";
      case "pr_open": return "#" + b.pr + " is not merged";
      case "pr_unverified": return "#" + b.pr + " is not observed yet; what was typed or reported counts for nothing";
      case "pr_not_found": return "#" + b.pr + " is not on the forge (a mistyped number, or a moved repository)";
      case "pr_mismatch": return "#" + b.pr + ": the observed head differs from the reported one";
      case "group_incomplete": return "the group " + b.tasks.join(" + ") + " does not ship complete";
      case "checklist_open": return "checklist item " + b.item + " is open";
      default: {
        const details = Object.keys(b).filter((k) => k !== "reason").map((k) => k + " " + JSON.stringify(b[k]));
        return b.reason + (details.length ? " (" + details.join(", ") + ")" : "");
      }
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

  function edges(label, ids, byId, frozen) {
    if (!ids || !ids.length) return null;
    if (frozen) return h("div", { class: "deps" }, h("span", { class: "label" }, label), h("ul", null, ids.map((id) => h("li", null, id))));
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

  // One pull request as the hub has it. Only what the forge probe observed
  // is a fact; a typed or reported state is shown as a claim beside
  // "unverified" (docs/api.md §6.7).
  function prState(pr) {
    if (pr.found === false) return h("td", { class: "pr-missing" }, "not on the forge");
    if (!pr.observed_at) {
      return h("td", { class: "pr-unverified" }, "unverified",
        pr.state ? h("span", { class: "muted" }, " · " + pr.source + " as " + pr.state) : null);
    }
    return h("td", { class: "pr-" + pr.state }, pr.state || "—");
  }

  function pullRequests(rel) {
    const prs = rel.pull_requests || [];
    if (!prs.length) return h("p", { class: "muted" }, "No pull requests yet: they come from the shipped cards' reports, or are typed in.");
    return h("table", { class: "prs" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, "PR"), h("th", { scope: "col" }, "State"),
        h("th", { scope: "col" }, "Checks"), h("th", { scope: "col" }, "Observed"))),
      h("tbody", null, prs.map((pr) => h("tr", null,
        h("td", null, safeUrl(pr.url) ? h("a", { href: safeUrl(pr.url), rel: "noopener noreferrer" }, "#" + pr.number) : "#" + pr.number,
          " " + (pr.title || ""), h("span", { class: "muted" }, " · " + pr.source + (pr.task_id ? " by " + pr.task_id : ""))),
        prState(pr),
        h("td", { class: "checks-" + pr.checks }, pr.observed_at && pr.checks ? pr.checks : "—"),
        h("td", null, pr.observed_at ? formatAgo(pr.observed_at) + (pr.head_sha ? " @ " + pr.head_sha : "") : "never")))));
  }

  // The connected ships_with components: they ship together or not at all.
  // Complete only by the hub's word: green when the release is ready, amber
  // when the hub names the group incomplete, neither while it observes
  // nothing. A member outside the release's depends_on is said so; a live
  // status is shown only for an open release, never in a frozen record.
  function shipGroups(c, byId, closed) {
    const rel = c.release;
    const groups = rel.groups || [];
    if (!groups.length) return null;
    const r = rel.readiness || { ready: false, blocking: [] };
    const incomplete = new Set((r.blocking || [])
      .filter((b) => b.reason === "group_incomplete").map((b) => (b.tasks || []).join(" ")));
    const shipped = new Set(c.depends_on || []);
    const member = (id) => id
      + (shipped.has(id) ? "" : " (not in this release)")
      + (!closed && byId[id] ? " (" + status(byId[id].status) + ")" : "");
    return h("div", { class: "deps groups" },
      h("span", { class: "label" }, "Ship together"),
      h("ul", null, groups.map((g) => h("li", {
        class: r.ready ? "met" : (incomplete.has(g.join(" ")) ? "unmet" : "unknown"),
      }, g.map(member).join(" + ")))));
  }

  function tagLine(rel) {
    const name = rel.tag ? rel.tag.name : "v" + rel.version;
    if (!rel.tag || !rel.tag.observed_at) return h("p", { class: "muted" }, "Tag " + name + ": not observed");
    return h("p", { class: "muted" }, "Tag " + name + ": "
      + (rel.tag.found ? "on the forge" + (rel.tag.sha ? " @ " + rel.tag.sha : "") : "not on the forge")
      + " · " + formatAgo(rel.tag.observed_at));
  }

  function release(ctx, c, byId, closed) {
    const rel = c.release;
    const r = rel.readiness || { ready: false, blocking: [] };
    const noProbe = r.blocking.some((b) => b.reason === "probe_not_configured");
    return [
      closed ? h("p", { class: "muted" }, "Closed: its pull requests, groups and readiness are the record frozen when it closed; "
        + "later changes do not alter them.") : null,
      pullRequests(rel),
      shipGroups(c, byId, closed),
      rel.checklist && rel.checklist.length
        ? h("ul", { class: "checklist" }, rel.checklist.map((item) =>
          h("li", { class: item.done ? "met" : "unmet" }, (item.done ? "✓ " : "○ ") + item.text,
            item.done && item.by ? h("span", { class: "muted" }, " · " + ctx.nameOf(item.by) + (item.at ? " " + formatAgo(item.at) : "")) : null)))
        : null,
      r.ready
        ? h("div", { class: "readiness ready" },
          c.status === "done"
            ? h("strong", null, "Shipped: it was ready when it closed.")
            : [h("strong", null, "Ready to tag"),
              h("span", null, " — every shipped card is done, every pull request observed merged, every group complete and the checklist done.")])
        : h("div", { class: "readiness not-ready" }, h("strong", null, "Not ready: "),
          h("ul", null, r.blocking.map((b) => h("li", null, blockingText(b, byId))))),
      noProbe && !closed
        ? h("p", { class: "flag" }, "Without a forge probe the hub cannot see this project's pull requests or tag, "
          + "so it never calls the release ready, and it can be cancelled but not marked done. The probe needs "
          + "the project's repository on a forge the hub has a token for.")
        : null,
      tagLine(rel),
    ];
  }

  // A contract's arbiter may be a role ("role:admin"): named in words.
  const arbiterName = (ctx, a) => (/^role:/.test(a || "") ? "the " + a.slice(5) + "s" : ctx.nameOf(a));

  function card(ctx, c, byId) {
    const frozen = c.kind === "release" && (c.status === "done" || c.status === "cancelled");
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
      edges(c.kind === "release" ? "Ships" : "Depends on", c.depends_on, byId, frozen),
      edges("Ships with", c.ships_with, byId),
      c.blocked_by_request
        ? h("p", { class: "flag" }, "Waits for ", h("a", { href: ctx.link("inbox") }, "an answer"), " (",
          h("span", { class: "request-id" }, c.blocked_by_request), ")")
        : null,
      c.contract
        ? h("p", { class: "muted" }, "Contract " + c.contract.state + " · arbiter " + arbiterName(ctx, c.contract.arbiter)
          + ((c.contract.watchers || []).length ? " · watched by " + c.contract.watchers.map(ctx.nameOf).join(", ") : ""))
        : null,
      checkpoint(c),
      report(c),
      c.kind === "release" && c.release ? release(ctx, c, byId, frozen) : null);
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
