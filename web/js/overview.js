// The project at a glance (#/p/<slug>/overview, docs/api.md §6.11): its
// repository and Keep the Why links, members and roles, the board's counts
// per column, open requests, and the latest reports. The project and its
// members are what the header already read; the counts come from one call,
// GET …/overview, read again when a card, a request or the probe changes.
// Every count links to where its items are.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatAgo } = M.dom;

  const COLUMNS = [["proposed", "Proposed"], ["open", "Open"], ["in_progress", "In progress"], ["blocked", "Blocked"],
    ["review", "Review"], ["done", "Done"], ["cancelled", "Cancelled"]];
  const PRIORITIES = [["urgent", "urgent"], ["high", "high"], ["normal", "normal"], ["low", "low"]];
  const ROLES = ["owner", "admin", "reviewer", "member", "proxy"];
  const PR_STATES = { merged: "merged", open: "open", closed: "closed without merge" };
  const REREAD = /^(task_|request_|probe_observed$)/;

  // A link from data: plain https only, in a new tab; anything else is text.
  function out(url, text) {
    const href = safeUrl(url);
    return href ? h("a", { href, rel: "noopener noreferrer", target: "_blank" }, text) : text;
  }

  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  function links(ctx) {
    const p = ctx.project;
    const admin = ctx.canAdmin || ctx.isOwner;
    const repo = p.repository && p.repository.url;
    const exp = p.keep_the_why_export;
    const rows = [h("dt", null, "Repository"),
      h("dd", null, repo ? out(repo, repo) : "No repository.",
        !repo && admin && ctx.openSettings ? [" ", h("button", { type: "button", class: "small", onclick: () => ctx.openSettings() }, "Set the repository")] : null)];
    rows.push(h("dt", null, "Keep the Why"));
    if (!exp) {
      rows.push(h("dd", null, "No Keep the Why dashboard is published.",
        admin ? h("span", { class: "muted" }, " The link comes from the dashboard-state line in the repository's .keep-the-why.") : null));
    } else {
      rows.push(h("dd", null, h("ul", { class: "overview-why" }, (exp.members || []).map((mm) => {
        const name = mm.path ? (mm.name || mm.path) : "the project";
        const sum = mm.summary || {};
        return h("li", null, mm.dashboard_url ? out(mm.dashboard_url, name) : name,
          typeof sum.attention === "number" ? h("span", { class: sum.attention ? "flag" : "muted" }, " · " + plural(sum.attention, "entry needs", "entries need") + " attention") : null,
          mm.error ? h("span", { class: "flag" }, " · " + (mm.error.reason || mm.error.code || "not read")) : null);
      }))));
    }
    if (p.policy && p.policy.preset) rows.push(h("dt", null, "Policy"), h("dd", null, p.policy.preset));
    return h("section", { class: "overview-part", "aria-labelledby": "overview-links" },
      h("h3", { id: "overview-links" }, "Links"), h("dl", { class: "facts" }, rows));
  }

  function members(ctx) {
    const list = ctx.members || [];
    const online = list.filter((m) => m.presence === "online").length;
    return h("section", { class: "overview-part", "aria-labelledby": "overview-members" },
      h("h3", { id: "overview-members" }, h("a", { href: ctx.link("members") }, "Members"), h("span", { class: "count" }, String(list.length))),
      list.length
        ? [h("p", { class: "muted" }, plural(list.filter((m) => m.kind === "human").length, "human", "humans") + ", "
            + plural(list.filter((m) => m.kind === "agent").length, "agent", "agents") + "; " + online + " online."),
          h("dl", { class: "facts" }, ROLES.filter((r) => list.some((m) => m.role === r)).map((r) => [
            h("dt", null, r),
            h("dd", null, list.filter((m) => m.role === r).map((m, i) => [i ? ", " : null, m.display_name])),
          ]))]
        : h("p", { class: "muted" }, "No members."));
  }

  function board(ctx, o) {
    const counts = (o.board && o.board.counts) || {};
    const total = COLUMNS.reduce((n, [s]) => n + (counts[s] || 0), 0);
    return h("section", { class: "overview-part", "aria-labelledby": "overview-board" },
      h("h3", { id: "overview-board" }, h("a", { href: ctx.link("board") }, "Board")),
      total
        ? h("ul", { class: "overview-counts" }, COLUMNS.map(([s, label]) => h("li", { "data-status": s },
          h("a", { href: ctx.link("board") }, h("span", { class: "n" }, String(counts[s] || 0)), " " + label))))
        : h("p", { class: "muted" }, "No cards yet."),
      o.board && o.board.closed_after ? h("p", { class: "hint" }, "Done and cancelled: the last " + M.boardWindowDays + " days, as on the board.") : null);
  }

  function requests(ctx, o) {
    const r = o.requests || {};
    return h("section", { class: "overview-part", "aria-labelledby": "overview-requests" },
      h("h3", { id: "overview-requests" }, h("a", { href: ctx.link("inbox") }, "Open requests"), h("span", { class: "count" }, String(r.open || 0))),
      r.open
        ? [h("p", null, h("a", { href: ctx.link("inbox") }, plural(r.to_me || 0, "is", "are") + " for you"),
            r.oldest_open_at ? h("span", { class: "muted" }, " · the oldest asked " + formatAgo(r.oldest_open_at)) : null),
          h("p", { class: "muted" }, PRIORITIES.filter(([k]) => (r.by_priority || {})[k]).map(([k, l]) => r.by_priority[k] + " " + l).join(", "))]
        : h("p", { class: "muted" }, "Nothing waits for an answer."));
  }

  function reports(ctx, o) {
    const list = o.reports || [];
    return h("section", { class: "overview-part", "aria-labelledby": "overview-reports" },
      h("h3", { id: "overview-reports" }, "Latest reports"),
      list.length
        ? h("ol", { class: "overview-reports" }, list.map((r) => h("li", null,
          M.avatar({ id: r.reported_by.member_id, avatar_url: r.reported_by.avatar_url }, 20),
          h("span", null, " " + r.reported_by.display_name + " · "),
          h("a", { href: ctx.link("board") }, h("span", { class: "card-id" }, r.task.id), " " + r.task.title),
          h("span", { class: "muted" }, " · " + formatAgo(r.reported_at)),
          r.pr ? h("span", null, " · ", out(r.pr.url, "PR #" + r.pr.number), r.pr_state ? " " + (PR_STATES[r.pr_state] || r.pr_state) : "") : null,
          !r.code ? h("span", { class: "muted" }, " · no code") : null,
          r.mismatch ? h("span", { class: "flag" }, " · the pull request does not match what was reported") : null)))
        : h("p", { class: "muted" }, "No card has been reported yet."));
  }

  M.views.overview = async function (ctx, root) {
    const since = new Date(Date.now() - M.boardWindowDays * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const path = ctx.base + "/overview?closed_after=" + encodeURIComponent(since);
    const status = M.statusLine();
    const box = h("div", { class: "overview" });
    // The links and members come from what the header holds; only the
    // counts need the overview call, and a failed one is said where they go.
    function draw(o, err) {
      append(clear(box), links(ctx), members(ctx),
        o ? [board(ctx, o), requests(ctx, o), reports(ctx, o)]
          : h("p", { class: "send-status failed" }, "The counts could not be read: "
            + (err.status === 404 ? "this hub has no overview yet." : err.message)));
    }
    try {
      draw(await M.api.get(path));
    } catch (err) {
      draw(null, err);
    }
    append(root, h("h2", null, "Overview"), status.el, box);
    // A summary is not read line by line: it is drawn again in place.
    let reading = false;
    ctx.onEvents(async (events) => {
      if (reading || !events.some((e) => REREAD.test(e.kind))) return;
      reading = true;
      try {
        draw(await M.api.get(path));
        status.done();
      } catch (err) {
        status.fail("Could not refresh: ", err);
      } finally {
        reading = false;
      }
    });
  };
})(window.Maity);
