// The project at a glance (/<owner>/<slug>/overview, docs/api.md §6.11): its
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
  const PR_STATES = { merged: "merged", open: "open", closed: "closed without merge" };
  const REREAD = /^(task_|request_|probe_observed$)/;
  const NARROW_MS = 60000;

  // A link from data: plain https only, in a new tab; anything else is text.
  // key: the control's name across redraws, so the focus can come back to it.
  function out(url, text, key) {
    const href = safeUrl(url);
    return href ? h("a", { href, rel: "noopener noreferrer", target: "_blank", "data-key": key }, text) : text;
  }

  const CONTRACT_PATH = "docs/api.md";
  // A file's page on the forge at the default branch: GitHub and GitLab
  // only, whose path shapes are known; anything else gets no link.
  function contractUrl(repo) {
    const base = repo && safeUrl(repo.url) ? String(repo.url).replace(/\.git$/, "").replace(/\/+$/, "") : null;
    if (!base || !repo.default_branch) return null;
    const branch = encodeURIComponent(repo.default_branch);
    if (repo.forge === "github") return base + "/blob/" + branch + "/" + CONTRACT_PATH;
    if (repo.forge === "gitlab") return base + "/-/blob/" + branch + "/" + CONTRACT_PATH;
    return null;
  }

  const plural = (n, one, many) => n + " " + (n === 1 ? one : many);

  // A panel's head (the designer's handover, #6484): the heading, quiet
  // facts beside it, and the panel's way onward at the row's right end, so
  // a heading never looks like a link.
  function head(id, title, facts, onward) {
    return h("div", { class: "overview-head" }, h("h3", { id }, title),
      facts ? h("span", { class: "muted" }, "· " + facts) : null,
      onward ? h("span", { class: "overview-onward" }, onward) : null);
  }

  // The project: its repository, policy and Keep the Why, each part of
  // the latter a pill with a dot (green, amber with what needs attention,
  // red with why it was not read).
  function project(ctx) {
    const p = ctx.project;
    const admin = ctx.canAdmin || ctx.isOwner;
    const repo = p.repository && p.repository.url;
    const exp = p.keep_the_why_export;
    const rows = [h("dt", null, "Repository"),
      h("dd", null, repo ? out(repo, String(repo).replace(/^https:\/\//, ""), "repo") : "No repository.",
        !repo && admin && ctx.openSettings ? [" ", h("button", { type: "button", class: "small", "data-key": "set-repo", onclick: () => ctx.openSettings() }, "Set the repository")] : null)];
    if (p.policy && p.policy.preset) rows.push(h("dt", null, "Policy"), h("dd", null, p.policy.preset));
    // The contract on the forge at the default branch (the maintainer's
    // wish, tsk-yhbmz7mjng7n step 1); read inside Maity once the hub serves it.
    const contract = contractUrl(p.repository);
    if (contract) rows.push(h("dt", null, "Contract"), h("dd", null, out(contract, CONTRACT_PATH, "contract")));
    rows.push(h("dt", null, "Keep the Why"));
    if (!exp) {
      rows.push(h("dd", null, "No Keep the Why dashboard is published.",
        admin ? h("span", { class: "muted" }, " The link comes from the dashboard-state line in the repository's .keep-the-why.") : null));
    } else {
      rows.push(h("dd", null, h("ul", { class: "overview-why" }, (exp.members || []).map((mm) => {
        const name = mm.path ? (mm.name || mm.path) : "the project";
        const sum = mm.summary || {};
        const attention = typeof sum.attention === "number" ? sum.attention : null;
        const tone = mm.error ? "pill-bad" : attention ? "pill-warn" : "pill-ok";
        const words = [name,
          attention ? " · " + plural(attention, "entry needs", "entries need") + " attention" : "",
          mm.error ? " · " + (mm.error.reason || mm.error.code || "not read") : ""].join("");
        const href = safeUrl(mm.dashboard_url);
        return h("li", null, href
          ? h("a", { class: "pill " + tone, href, rel: "noopener noreferrer", target: "_blank", "data-key": "why:" + mm.path }, words)
          : h("span", { class: "pill " + tone }, words));
      })),
      // A family cut at the hub's limit (§11.3) and a failed read of it are said.
      exp.family_truncated ? h("p", { class: "flag" }, "Only part of the family is shown: it has more parts than the hub reads.") : null,
      exp.error ? h("p", { class: "flag" }, "The last read failed: " + (exp.error.reason || exp.error.code || "unknown") + ".") : null));
    }
    return h("section", { class: "overview-part", "aria-labelledby": "overview-links" },
      head("overview-links", "Project"), h("dl", { class: "facts" }, rows));
  }

  // The README badge (§6.20) as it stands: its state, the badge as the hub
  // serves it, the snippet with Copy. It is changed in Project settings,
  // where a change takes its logged reason.
  function badge(ctx) {
    const policy = ctx.project.policy || {};
    if (!("badge" in policy)) return null;
    const state = policy.badge || "off";
    const names = { off: "Off", members: "Members", agents_online: "Agents online" };
    const admin = (ctx.canAdmin || ctx.isOwner) && ctx.me.kind === "human";
    const raw = window.location && window.location.origin;
    const origin = raw && raw !== "null" ? raw : "https://<hub>";
    const path = "/badge/" + M.api.projectPath(ctx.slug) + ".svg";
    const snippet = "[![maity](" + origin + path + ")](" + origin + ctx.link("overview") + ")";
    const copy = h("button", { type: "button", class: "small", "data-key": "badge-copy", "aria-label": "Copy the badge snippet" }, "Copy");
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(snippet); copy.textContent = "Copied"; } catch (err) { copy.textContent = "Copy failed: select the line"; }
      window.setTimeout(() => { copy.textContent = "Copy"; }, 2000);
    });
    return h("section", { class: "overview-part", "aria-labelledby": "overview-badge" },
      head("overview-badge", "README badge", null,
        admin ? h("a", { href: ctx.link("settings"), "data-key": "badge-settings" }, "Change in Project settings") : null),
      h("ul", { class: "overview-badge-states", "aria-label": "Badge" }, Object.keys(names).map((k) =>
        h("li", { class: "pill " + (k === state ? "pill-on" : "pill-idle"), "aria-current": k === state ? "true" : null }, names[k]))),
      state === "off"
        ? h("p", { class: "muted" }, "Off: the badge address answers 'not found'. Turning it on shows counts publicly, never names.")
        : [h("img", { class: "badge-preview", src: path + "?v=" + encodeURIComponent(ctx.project.rules_version || 0), alt: "The project's badge as the hub serves it" }),
          h("p", { class: "muted" }, "Public at " + path + " · counts only")],
      // A box that scrolls sideways is reachable by keyboard, and named.
      h("div", { class: "overview-snippet" }, h("code", { tabindex: "0", role: "region", "aria-label": "Badge snippet for the README" }, snippet), copy));
  }

  // The team, per role: one row of member chips each, the counts above.
  function members(ctx) {
    const list = ctx.members || [];
    const humans = list.filter((m) => m.kind === "human").length;
    const agents = list.filter((m) => m.kind === "agent").length;
    const online = list.filter((m) => m.presence === "online").length;
    return h("section", { class: "overview-part overview-team", "aria-labelledby": "overview-members" },
      head("overview-members", "Team", list.length ? plural(humans, "human", "humans") + ", " + plural(agents, "agent", "agents") + " · " + online + " online" : null,
        h("a", { href: ctx.link("members"), "data-key": "members" }, "All members")),
      list.length
        // By trust (§2.3); each chip names its role on hover.
        ? h("div", { class: "overview-roles" }, M.trust.TRUSTS.filter((t) => list.some((m) => m.trust === t)).map((t) =>
          h("div", { class: "overview-role" }, h("span", { class: "overview-role-name muted" }, t),
            h("div", { class: "overview-chips" }, list.filter((m) => m.trust === t).map((m) => M.dom.memberChip(ctx, m))))))
        : h("p", { class: "muted" }, "No members."));
  }

  // The board as one stacked bar, one segment per column, and a legend
  // under it whose every item links to the board.
  function board(ctx, o) {
    const counts = (o.board && o.board.counts) || {};
    const total = COLUMNS.reduce((n, [s]) => n + (counts[s] || 0), 0);
    const bar = h("div", { class: "overview-bar", role: "img",
      "aria-label": COLUMNS.map(([s, label]) => (counts[s] || 0) + " " + label.toLowerCase()).join(", ") });
    COLUMNS.forEach(([s]) => {
      if (!counts[s]) return;
      const seg = h("span", { class: "overview-seg seg-" + s });
      // CSSOM, never a style attribute (the page's CSP).
      seg.style.flex = String(counts[s]);
      append(bar, seg);
    });
    return h("section", { class: "overview-part", "aria-labelledby": "overview-board" },
      head("overview-board", "Board", total ? plural(total, "card", "cards") : null,
        h("a", { href: ctx.link("board"), "data-key": "board" }, "Open the board")),
      total
        ? [bar, h("ul", { class: "overview-counts" }, COLUMNS.map(([s, label]) => h("li", { "data-status": s },
          h("a", { href: ctx.link("board"), "data-key": "count:" + s },
            h("span", { class: "n" }, String(counts[s] || 0)), h("span", { class: "overview-swatch seg-" + s, "aria-hidden": "true" }), " " + label))))]
        : h("p", { class: "muted" }, "No cards yet."),
      o.board && o.board.closed_after ? h("p", { class: "hint" }, "Done and cancelled: the last " + M.boardWindowDays + " days, as on the board.") : null);
  }

  // What waits for the reader, first: the requests for them as one big
  // number, the inbox one click away, the priorities and the oldest under it.
  function requests(ctx, o) {
    const r = o.requests || {};
    const inbox = h("a", { class: "button primary", href: ctx.link("inbox"), "data-key": "requests" }, "Open the inbox");
    let main;
    if (r.to_me) {
      main = h("div", { class: "overview-waiting" },
        h("a", { class: "overview-big", href: ctx.link("inbox"), "data-key": "mine" },
          h("span", { class: "big" }, String(r.to_me)), " " + (r.to_me === 1 ? "open request for you" : "open requests for you")),
        inbox);
    } else if (r.open) {
      main = h("div", { class: "overview-waiting" },
        h("p", null, h("a", { href: ctx.link("inbox"), "data-key": "mine" }, "Nothing for you"), " · " + r.open + " open for others"), inbox);
    } else {
      main = h("p", { class: "muted" }, "Nothing waits for an answer.");
    }
    const prios = PRIORITIES.filter(([k]) => (r.by_priority || {})[k]);
    return h("section", { class: "overview-part", "aria-labelledby": "overview-requests" },
      head("overview-requests", "Waiting for you", r.open ? plural(r.open, "open request", "open requests") : null),
      main,
      r.open
        ? h("p", { class: "overview-prios" }, prios.map(([k, l]) => h("span", { class: "pill prio-pill" + (k === "high" || k === "urgent" ? " prio-pill-high" : "") }, r.by_priority[k] + " " + l)),
          r.oldest_open_at ? h("span", { class: "muted" }, " · the oldest asked " + formatAgo(r.oldest_open_at)) : null)
        : null);
  }

  function reports(ctx, o) {
    const list = o.reports || [];
    return h("section", { class: "overview-part overview-latest", "aria-labelledby": "overview-reports" },
      head("overview-reports", "Latest reports"),
      list.length
        ? h("ol", { class: "overview-reports" }, list.map((r) => h("li", null,
          h("span", { class: "overview-report-avatar" }, M.avatar({ id: r.reported_by.member_id, avatar_url: r.reported_by.avatar_url }, 22)),
          h("div", { class: "overview-report-body" },
            // The board has no card route yet: a report links to the board.
            h("a", { href: ctx.link("board"), "data-key": "report:" + r.task.id }, h("span", { class: "card-id" }, r.task.id), " " + r.task.title),
            h("div", { class: "overview-report-meta muted" },
              M.dom.memberRef(ctx, r.reported_by, { text: "handle", instance: r.reported_by.instance }),
              " · " + formatAgo(r.reported_at),
              r.pr ? [" · ", out(r.pr.url, "PR #" + r.pr.number, "pr:" + r.task.id),
                r.pr_state ? [" ", h("span", { class: "pill pr-state pr-" + r.pr_state }, PR_STATES[r.pr_state] || r.pr_state)] : null] : null,
              !r.code ? " · no code" : null),
            r.mismatch ? h("p", { class: "flag" }, "The pull request does not match what was reported.") : null))))
        : h("p", { class: "muted" }, "No card has been reported yet."));
  }

  // The order (the designer's handover): what needs the reader, then the
  // state, then the facts; one column on a phone in the same order.
  function layout(ctx, parts) {
    return [
      h("div", { class: "overview-row overview-row-1" }, parts.requests, parts.board),
      h("div", { class: "overview-row overview-row-2" }, members(ctx), parts.reports),
      h("div", { class: "overview-row overview-row-3" }, project(ctx), badge(ctx)),
      // Who reports to whom (js/org.js), once the Organisation tab.
      M.org ? h("div", { class: "overview-row overview-row-4" }, M.org.section(ctx)) : null,
    ];
  }

  M.views.overview = async function (ctx, root) {
    const since = new Date(Date.now() - M.boardWindowDays * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const path = ctx.base + "/overview?closed_after=" + encodeURIComponent(since);
    const status = M.statusLine();
    const box = h("div", { class: "overview" });
    // The links and members come from what the header holds; only the
    // counts need the overview call, and a failed one is said where they go.
    // A redraw keeps the focus on the same control (its data-key).
    let last = [null, null];
    function draw(o, err) {
      last = [o, err];
      const had = document.activeElement && box.contains(document.activeElement) ? document.activeElement.getAttribute("data-key") : null;
      // A hub without the overview (404) is said quietly, as a fact of that
      // hub, never as an error; any other failure is one. Either stands
      // where the counts would.
      const missing = !o && (err.notOnHub ? h("p", { class: "muted overview-missing" }, "This hub has no overview yet, so no counts are shown here.")
        : h("p", { class: "send-status failed" }, "The counts could not be read: " + err.message));
      append(clear(box), layout(ctx, o
        ? { requests: requests(ctx, o), board: board(ctx, o), reports: reports(ctx, o) }
        : { requests: missing, board: null, reports: null }));
      const again = had && Array.from(box.querySelectorAll("a, button")).find((e) => e.getAttribute("data-key") === had);
      if (again) again.focus();
    }
    // Not on this hub: said once, and its timers and events ask no more.
    const absent = () => M.api.absent.has("GET", path);
    try {
      if (absent()) throw new M.api.ApiError("not on this hub", 404, path, "not_found");
      draw(await M.api.get(path));
    } catch (err) {
      if (absent() || await M.api.missingRoute(err, "GET", path)) { err.notOnHub = true; M.api.absent.note("GET", path); }
      draw(null, err);
    }
    append(root, h("h2", null, "Overview"), status.el, box);
    // A summary is not read line by line: it is drawn again in place. A
    // trigger during a read runs one more read after it, so none is lost.
    let reading = false;
    let pendingRead = false;
    async function reread() {
      if (absent()) return;
      if (reading) { pendingRead = true; return; }
      reading = true;
      try {
        draw(await M.api.get(path));
        status.done();
      } catch (err) {
        if (await M.api.missingRoute(err, "GET", path)) { err.notOnHub = true; M.api.absent.note("GET", path); draw(null, err); status.done(); } else status.fail("Could not refresh: ", err);
      } finally {
        reading = false;
        if (pendingRead) { pendingRead = false; reread(); }
      }
    }
    // The organisation follows the members: they are read again, the
    // counts drawn as they were.
    ctx.onEvents((events) => {
      if (events.some((e) => REREAD.test(e.kind))) reread();
      if (events.some((e) => /^member_/.test(e.kind))) {
        M.api.getAll(ctx.base + "/members").then((r) => { M.withMembers(ctx, r.items); draw(last[0], last[1]); }, (err) => status.fail("Could not read the members again: ", err));
      }
    });
    // §6.11: a viewer who is neither owner nor admin is in few events'
    // audiences, so the view also re-reads every 60 seconds and when the
    // tab comes back; the timer ends with the view, the listener with it.
    if (!(ctx.canAdmin || ctx.isOwner)) {
      ctx.every(NARROW_MS, reread);
      // The tab shown again, or its window focused again (another window was
      // in front while the tab stayed visible); both end with the view.
      const back = () => {
        if (!root.isConnected && root.isConnected !== undefined) {
          document.removeEventListener("visibilitychange", back);
          window.removeEventListener("focus", back);
          return;
        }
        if (document.visibilityState !== "hidden") reread();
      };
      document.addEventListener("visibilitychange", back);
      window.addEventListener("focus", back);
    }
  };
})(window.Maity);
