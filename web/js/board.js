// (2) The board: cards by status, with claim holder and dependencies.
// Releases are a card kind with their pull requests as the hub observed
// them on the forge.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, formatAgo, formatTime } = M.dom;

  const COLUMNS = [
    ["open", "Open"],
    ["in_progress", "In progress"],
    ["blocked", "Blocked"],
    ["review", "Review"],
    ["done", "Done"],
  ];

  // Ready when every dependency is done and every pull request is merged
  // with green checks, by observed state only.
  function releaseReadiness(card, byId) {
    const reasons = [];
    card.depends_on.forEach((id) => {
      const dep = byId[id];
      if (!dep) reasons.push(id + " is unknown");
      else if (dep.status !== "done") reasons.push(id + " is " + dep.status.replace("_", " "));
    });
    (card.release.pull_requests || []).forEach((pr) => {
      if (pr.state !== "merged") reasons.push("#" + pr.number + " is " + pr.state);
      else if (pr.checks !== "success") reasons.push("#" + pr.number + " checks " + pr.checks);
    });
    return reasons;
  }

  function claimLine(ctx, claim) {
    if (!claim) return h("p", { class: "claim unclaimed" }, "Unclaimed");
    return h("p", { class: "claim" },
      "Claimed by ", h("strong", null, ctx.nameOf(claim.holder)), " · " + formatAgo(claim.since),
      claim.lease_until ? h("span", { class: "lease" }, " · lease until " + formatTime(claim.lease_until)) : null);
  }

  function dependencies(card, byId) {
    if (!card.depends_on.length) return null;
    return h("div", { class: "deps" },
      h("span", { class: "label" }, "Depends on"),
      h("ul", null, card.depends_on.map((id) => {
        const dep = byId[id];
        const done = dep && dep.status === "done";
        return h("li", { class: done ? "met" : "unmet" },
          id + (dep ? " — " + dep.title + " (" + dep.status.replace("_", " ") + ")" : " (unknown)"));
      })));
  }

  function pullRequests(card) {
    const prs = card.release.pull_requests || [];
    if (!prs.length) return h("p", { class: "muted" }, "No pull requests yet.");
    return h("table", { class: "prs" },
      h("thead", null, h("tr", null,
        h("th", { scope: "col" }, "PR"), h("th", { scope: "col" }, "State"),
        h("th", { scope: "col" }, "Checks"), h("th", { scope: "col" }, "Observed"))),
      h("tbody", null, prs.map((pr) => h("tr", null,
        h("td", null, "#" + pr.number + " " + pr.title),
        h("td", { class: "pr-" + pr.state }, pr.state),
        h("td", { class: "checks-" + pr.checks }, pr.checks),
        h("td", null, formatAgo(pr.observed_at) + (pr.head_sha ? " @ " + pr.head_sha : ""))))));
  }

  function card(ctx, c, byId) {
    const el = h("article", { class: "card card-" + c.kind, "aria-label": c.title },
      h("header", null,
        h("span", { class: "card-id" }, c.id),
        c.kind === "release" ? h("span", { class: "badge release" }, "Release " + c.release.version) : null,
        c.scope ? h("span", { class: "scope" }, c.scope) : null),
      h("h3", null, c.title),
      claimLine(ctx, c.claim),
      dependencies(c, byId),
      c.blocked_by_request
        ? h("p", { class: "flag" }, "Waits for ", h("a", { href: "#/inbox" }, "your answer"), " (" + c.blocked_by_request + ")")
        : null);
    if (c.kind === "release") {
      const reasons = releaseReadiness(c, byId);
      el.append(pullRequests(c),
        reasons.length
          ? h("div", { class: "readiness not-ready" }, h("strong", null, "Not ready: "), reasons.join("; "))
          : h("div", { class: "readiness ready" }, h("strong", null, "Ready to tag")));
    }
    return el;
  }

  M.views.board = async function (ctx, root) {
    const tasks = await M.api.get(ctx.base + "/tasks");
    const byId = {};
    tasks.items.forEach((t) => { byId[t.id] = t; });
    const known = new Set(COLUMNS.map(([s]) => s));
    const other = tasks.items.filter((t) => !known.has(t.status));

    root.append(h("h2", null, "Board"),
      h("div", { class: "columns" },
        COLUMNS.map(([status, label]) => {
          const cards = tasks.items.filter((t) => t.status === status);
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
