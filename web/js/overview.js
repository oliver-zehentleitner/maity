// The project at a glance (/<owner>/<slug>/overview, docs/api.md §6.11), in
// three tabs: Summary (what waits for the reader, the board's counts per
// column, the team, the latest reports), Swarm (overview/swarm, the swarm
// statistics, js/swarm.js, §6.22) and Project (overview/project: the
// repository, Keep the Why links and the README badge). The project and
// its members are what the header already read; the counts come from one
// call, GET …/overview, read on Summary only and again when a card, a
// request or the probe changes. Every count links to where its items are.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl, formatAgo } = M.dom;

  const COLUMNS = ["proposed", "open", "in_progress", "blocked", "review", "done", "cancelled"];
  // Getters: a label is the catalog's when shown.
  const COLUMN_LABELS = {
    get proposed() { return M.t("overview.column.proposed"); },
    get open() { return M.t("overview.column.open"); },
    get in_progress() { return M.t("overview.column.in_progress"); },
    get blocked() { return M.t("overview.column.blocked"); },
    get review() { return M.t("overview.column.review"); },
    get done() { return M.t("overview.column.done"); },
    get cancelled() { return M.t("overview.column.cancelled"); },
  };
  // A column's count as a screen reader hears it in the bar's name.
  const COLUMN_COUNTS = {
    proposed: (n) => M.t("overview.bar.proposed", { count: n }),
    open: (n) => M.t("overview.bar.open", { count: n }),
    in_progress: (n) => M.t("overview.bar.in_progress", { count: n }),
    blocked: (n) => M.t("overview.bar.blocked", { count: n }),
    review: (n) => M.t("overview.bar.review", { count: n }),
    done: (n) => M.t("overview.bar.done", { count: n }),
    cancelled: (n) => M.t("overview.bar.cancelled", { count: n }),
  };
  const PRIORITIES = ["urgent", "high", "normal", "low"];
  const PRIORITY_COUNTS = {
    urgent: (n) => M.t("overview.prio.urgent", { count: n }),
    high: (n) => M.t("overview.prio.high", { count: n }),
    normal: (n) => M.t("overview.prio.normal", { count: n }),
    low: (n) => M.t("overview.prio.low", { count: n }),
  };
  const PR_STATES = {
    get merged() { return M.t("overview.pr.merged"); },
    get open() { return M.t("overview.pr.open"); },
    get closed() { return M.t("overview.pr.closed"); },
  };
  const REREAD = /^(task_|request_|probe_observed$)/;
  const NARROW_MS = 60000;
  // The tabs (the maintainer, 2026-10-30: one page was too full). Getters:
  // the labels are the catalog's when shown.
  const TABS = [
    { key: "", get label() { return M.t("overview.tab.summary"); } },
    { key: "swarm", get label() { return M.t("overview.tab.swarm"); }, when: () => !!M.swarm },
    { key: "project", get label() { return M.t("overview.tab.project"); } },
  ];

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
    const rows = [h("dt", null, M.t("overview.project.repository")),
      h("dd", null, repo ? out(repo, String(repo).replace(/^https:\/\//, ""), "repo") : M.t("overview.project.no_repository"),
        !repo && admin && ctx.openSettings ? [" ", h("button", { type: "button", class: "small", "data-key": "set-repo", onclick: () => ctx.openSettings() }, M.t("overview.project.set_repository"))] : null)];
    rows.push(h("dt", null, M.t("overview.project.state")), h("dd", null, ctx.stateBadge(p.state, p.state_note), p.released_at ? [" ", ctx.releasedMark(p)] : null));
    if (p.policy && p.policy.preset) rows.push(h("dt", null, M.t("overview.project.policy")), h("dd", null, p.policy.preset));
    // The contract on the forge at the default branch (the maintainer's
    // wish, tsk-yhbmz7mjng7n step 1); read inside Maity once the hub serves it.
    const contract = contractUrl(p.repository);
    if (contract) rows.push(h("dt", null, M.t("overview.project.contract")), h("dd", null, out(contract, CONTRACT_PATH, "contract")));
    rows.push(h("dt", null, M.t("overview.project.why")));
    if (!exp) {
      rows.push(h("dd", null, M.t("overview.project.no_why"),
        admin ? h("span", { class: "muted" }, " " + M.t("overview.project.why_source")) : null));
    } else {
      rows.push(h("dd", null, h("ul", { class: "overview-why" }, (exp.members || []).map((mm) => {
        const name = mm.path ? (mm.name || mm.path) : M.t("overview.project.why_root");
        const sum = mm.summary || {};
        const attention = typeof sum.attention === "number" ? sum.attention : null;
        const tone = mm.error ? "pill-bad" : attention ? "pill-warn" : "pill-ok";
        const words = [name,
          attention ? " · " + M.t("overview.project.why_attention", { count: attention }) : "",
          mm.error ? " · " + (mm.error.reason || mm.error.code || M.t("overview.project.why_not_read")) : ""].join("");
        const href = safeUrl(mm.dashboard_url);
        return h("li", null, href
          ? h("a", { class: "pill " + tone, href, rel: "noopener noreferrer", target: "_blank", "data-key": "why:" + mm.path }, words)
          : h("span", { class: "pill " + tone }, words));
      })),
      // A family cut at the hub's limit (§11.3) and a failed read of it are said.
      exp.family_truncated ? h("p", { class: "flag" }, M.t("overview.project.why_truncated")) : null,
      exp.error ? h("p", { class: "flag" }, M.t("overview.project.why_failed", { reason: exp.error.reason || exp.error.code || "unknown" })) : null));
    }
    return h("section", { class: "overview-part", "aria-labelledby": "overview-links" },
      head("overview-links", M.t("overview.project.title")), h("dl", { class: "facts" }, rows));
  }

  // The README badge (§6.20) as it stands: its state, the badge as the hub
  // serves it, the snippet with Copy. It is changed in Project settings,
  // where a change takes its logged reason.
  function badge(ctx) {
    const policy = ctx.project.policy || {};
    const state = policy.badge || "off";
    const names = {
      get off() { return M.t("overview.badge.off"); },
      get members() { return M.t("overview.badge.members"); },
      get agents_online() { return M.t("overview.badge.agents_online"); },
    };
    const admin = (ctx.canAdmin || ctx.isOwner) && ctx.me.kind === "human";
    const raw = window.location && window.location.origin;
    const origin = raw && raw !== "null" ? raw : "https://<hub>";
    const path = "/badge/" + M.api.projectPath(ctx.slug) + ".svg";
    const snippet = "[![maity](" + origin + path + ")](" + origin + ctx.link("overview") + ")";
    const copy = h("button", { type: "button", class: "small", "data-key": "badge-copy", "aria-label": M.t("overview.badge.copy_label") }, M.t("overview.badge.copy"));
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(snippet); copy.textContent = M.t("overview.badge.copied"); } catch (err) { copy.textContent = M.t("overview.badge.copy_failed"); }
      window.setTimeout(() => { copy.textContent = M.t("overview.badge.copy"); }, 2000);
    });
    return h("section", { class: "overview-part", "aria-labelledby": "overview-badge" },
      head("overview-badge", M.t("overview.badge.title"), null,
        admin ? h("a", { href: ctx.link("settings"), "data-key": "badge-settings" }, M.t("overview.badge.change")) : null),
      h("ul", { class: "overview-badge-states", "aria-label": M.t("overview.badge.states") }, Object.keys(names).map((k) =>
        h("li", { class: "pill " + (k === state ? "pill-on" : "pill-idle"), "aria-current": k === state ? "true" : null }, names[k]))),
      state === "off"
        ? h("p", { class: "muted" }, M.t("overview.badge.off_hint"))
        : [h("img", { class: "badge-preview", src: path + "?v=" + encodeURIComponent(ctx.project.rules_version || 0), alt: M.t("overview.badge.preview") }),
          h("p", { class: "muted" }, M.t("overview.badge.public", { path }))],
      // A box that scrolls sideways is reachable by keyboard, and named.
      h("div", { class: "overview-snippet" }, h("code", { tabindex: "0", role: "region", "aria-label": M.t("overview.badge.snippet") }, snippet), copy));
  }

  // The team, per role: one row of member chips each, the counts above.
  function members(ctx) {
    const list = ctx.members || [];
    const humans = list.filter((m) => m.kind === "human").length;
    const agents = list.filter((m) => m.kind === "agent").length;
    const online = list.filter((m) => m.presence === "online").length;
    return h("section", { class: "overview-part", "aria-labelledby": "overview-members" },
      head("overview-members", M.t("overview.team.title"),
        list.length ? M.t("overview.team.facts", { humans: M.t("overview.team.humans", { count: humans }), agents: M.t("overview.team.agents", { count: agents }), online }) : null,
        h("a", { href: ctx.link("members"), "data-key": "members" }, M.t("overview.team.all"))),
      list.length
        // By trust (§2.3); each chip names its role on hover.
        ? h("div", { class: "overview-roles" }, M.trust.TRUSTS.filter((t) => list.some((m) => m.trust === t)).map((t) =>
          h("div", { class: "overview-role" }, h("span", { class: "overview-role-name muted" }, t),
            h("div", { class: "overview-chips" }, list.filter((m) => m.trust === t).map((m) => M.dom.memberChip(ctx, m))))))
        : h("p", { class: "muted" }, M.t("overview.team.none")));
  }

  // The board as one stacked bar, one segment per column, and a legend
  // under it whose every item links to the board.
  function board(ctx, o) {
    const counts = (o.board && o.board.counts) || {};
    const total = COLUMNS.reduce((n, s) => n + (counts[s] || 0), 0);
    const bar = h("div", { class: "overview-bar", role: "img",
      "aria-label": new Intl.ListFormat(M.i18n.language, { type: "unit" }).format(COLUMNS.map((s) => COLUMN_COUNTS[s](counts[s] || 0))) });
    COLUMNS.forEach((s) => {
      if (!counts[s]) return;
      const seg = h("span", { class: "overview-seg seg-" + s });
      // CSSOM, never a style attribute (the page's CSP).
      seg.style.flex = String(counts[s]);
      append(bar, seg);
    });
    return h("section", { class: "overview-part", "aria-labelledby": "overview-board" },
      head("overview-board", M.t("overview.board.title"), total ? M.t("overview.board.cards", { count: total }) : null,
        h("a", { href: ctx.link("board"), "data-key": "board" }, M.t("overview.board.open"))),
      total
        ? [bar, h("ul", { class: "overview-counts" }, COLUMNS.map((s) => h("li", { "data-status": s },
          h("a", { href: ctx.link("board"), "data-key": "count:" + s },
            h("span", { class: "n" }, String(counts[s] || 0)), h("span", { class: "overview-swatch seg-" + s, "aria-hidden": "true" }), " " + COLUMN_LABELS[s]))))]
        : h("p", { class: "muted" }, M.t("overview.board.none")),
      o.board && o.board.closed_after ? h("p", { class: "hint" }, M.t("overview.board.window", { count: M.boardWindowDays })) : null);
  }

  // What waits for the reader, first: the requests for them as one big
  // number, the inbox one click away, the priorities and the oldest under it.
  function requests(ctx, o) {
    const r = o.requests || {};
    const inbox = h("a", { class: "button primary", href: ctx.link("inbox"), "data-key": "requests" }, M.t("overview.requests.inbox"));
    let main;
    if (r.to_me) {
      main = h("div", { class: "overview-waiting" },
        h("a", { class: "overview-big", href: ctx.link("inbox"), "data-key": "mine" },
          h("span", { class: "big" }, String(r.to_me)), " " + M.t("overview.requests.for_you", { count: r.to_me })),
        inbox);
    } else if (r.open) {
      main = h("div", { class: "overview-waiting" },
        h("p", null, h("a", { href: ctx.link("inbox"), "data-key": "mine" }, M.t("overview.requests.nothing_for_you")),
          " · " + M.t("overview.requests.for_others", { count: r.open })), inbox);
    } else {
      main = h("p", { class: "muted" }, M.t("overview.requests.none"));
    }
    const prios = PRIORITIES.filter((k) => (r.by_priority || {})[k]);
    return h("section", { class: "overview-part", "aria-labelledby": "overview-requests" },
      head("overview-requests", M.t("overview.requests.title"), r.open ? M.t("overview.requests.open", { count: r.open }) : null),
      main,
      r.open
        ? h("p", { class: "overview-prios" }, prios.map((k) => h("span", { class: "pill prio-pill" + (k === "high" || k === "urgent" ? " prio-pill-high" : "") }, PRIORITY_COUNTS[k](r.by_priority[k]))),
          r.oldest_open_at ? h("span", { class: "muted" }, " · " + M.t("overview.requests.oldest", { ago: formatAgo(r.oldest_open_at) })) : null)
        : null);
  }

  function reports(ctx, o) {
    const list = o.reports || [];
    return h("section", { class: "overview-part overview-latest", "aria-labelledby": "overview-reports" },
      head("overview-reports", M.t("overview.reports.title")),
      list.length
        ? h("ol", { class: "overview-reports" }, list.map((r) => h("li", null,
          h("span", { class: "overview-report-avatar" }, M.avatar({ id: r.reported_by.member_id, avatar_url: r.reported_by.avatar_url }, 22)),
          h("div", { class: "overview-report-body" },
            // The board has no card route yet: a report links to the board.
            h("a", { href: ctx.link("board"), "data-key": "report:" + r.task.id }, h("span", { class: "card-id" }, r.task.id), " " + r.task.title),
            h("div", { class: "overview-report-meta muted" },
              M.dom.memberRef(ctx, r.reported_by, { text: "handle", instance: r.reported_by.instance }),
              " · " + formatAgo(r.reported_at),
              r.pr ? [" · ", out(r.pr.url, M.t("overview.reports.pr", { number: String(r.pr.number) }), "pr:" + r.task.id),
                r.pr_state ? [" ", h("span", { class: "pill pr-state pr-" + r.pr_state }, Object.hasOwn(PR_STATES, r.pr_state) ? PR_STATES[r.pr_state] : r.pr_state)] : null] : null,
              !r.code ? " · " + M.t("overview.reports.no_code") : null),
            r.mismatch ? h("p", { class: "flag" }, M.t("overview.reports.mismatch")) : null))))
        : h("p", { class: "muted" }, M.t("overview.reports.none")));
  }

  // Summary in the designer's order: what needs the reader, then the
  // state; one column on a phone in the same order. The team stands
  // beside Latest reports. The organisation is a tab of the Team page
  // (js/org.js), the facts and the swarm tabs of their own.
  function layout(ctx, tab, parts, swarm) {
    if (tab === "project") return h("div", { class: "overview-row overview-row-facts" }, project(ctx), badge(ctx));
    if (tab === "swarm") return h("div", { class: "overview-row overview-row-3" }, swarm);
    return [
      h("div", { class: "overview-row overview-row-1" }, parts.requests, parts.board),
      h("div", { class: "overview-row overview-row-2" }, h("div", { class: "overview-stack" }, members(ctx)), parts.reports),
    ];
  }

  function tabsNav(ctx, chosen) {
    return h("nav", { class: "view-tabs overview-tabs", "aria-label": M.t("overview.tabs.label") },
      TABS.filter((t) => !t.when || t.when()).map((t) =>
        h("a", { href: t.key ? ctx.link("overview", t.key) : ctx.link("overview"), class: "view-tab", "aria-current": t.key === chosen ? "page" : null }, t.label)));
  }

  // args[0]: the tab (overview/<tab>); none, or one not offered, is Summary.
  M.views.overview = async function (ctx, root, args) {
    const asked = args && args[0];
    const tab = TABS.some((t) => t.key === asked && t.key && (!t.when || t.when())) ? asked : "";
    const counts = tab === "";
    const since = new Date(Date.now() - M.boardWindowDays * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z");
    const path = ctx.base + "/overview?closed_after=" + encodeURIComponent(since);
    const status = M.statusLine();
    const box = h("div", { class: "overview" });
    // The swarm reads on its own, on its tab only, and is kept across the redraws below.
    const swarm = tab === "swarm" ? M.swarm.section(ctx) : null;
    // The links and members come from what the header holds; only the
    // counts need the overview call, and a failed one is said where they go.
    // A redraw keeps the focus on the same control (its data-key).
    let last = [null, null];
    function draw(o, err) {
      last = [o, err];
      const had = document.activeElement && box.contains(document.activeElement) ? document.activeElement.getAttribute("data-key") : null;
      // A failed read stands where the counts would.
      const missing = counts && !o && h("p", { class: "send-status failed" }, M.t("overview.counts_failed", { reason: err.message }));
      append(clear(box), layout(ctx, tab, !counts ? null : o
        ? { requests: requests(ctx, o), board: board(ctx, o), reports: reports(ctx, o) }
        : { requests: missing, board: null, reports: null }, swarm));
      const again = had && Array.from(box.querySelectorAll("a, button")).find((e) => e.getAttribute("data-key") === had);
      if (again) again.focus();
    }
    if (!counts) draw(null, null);
    else {
      try {
        draw(await M.api.get(path));
      } catch (err) {
        draw(null, err);
      }
    }
    append(root, h("h2", null, M.t("overview.title")), tabsNav(ctx, tab), status.el, box);
    // A summary is not read line by line: it is drawn again in place. A
    // trigger during a read runs one more read after it, so none is lost.
    let reading = false;
    let pendingRead = false;
    async function reread() {
      if (!counts) return;
      if (reading) { pendingRead = true; return; }
      reading = true;
      try {
        draw(await M.api.get(path));
        status.done();
      } catch (err) {
        status.fail(M.t("overview.refresh_failed"), err);
      } finally {
        reading = false;
        if (pendingRead) { pendingRead = false; reread(); }
      }
    }
    // The team follows the members: they are read again, the counts drawn
    // as they were.
    ctx.onEvents((events) => {
      if (events.some((e) => REREAD.test(e.kind))) reread();
      if (events.some((e) => /^member_/.test(e.kind))) {
        M.api.getAll(ctx.base + "/members").then((r) => { M.withMembers(ctx, r.items); draw(last[0], last[1]); }, (err) => status.fail(M.t("overview.members_failed"), err));
      }
    });
    // §6.11: a viewer who is neither owner nor admin is in few events'
    // audiences, so the view also re-reads every 60 seconds and when the
    // tab comes back; the timer ends with the view, the listener with it.
    if (counts && !(ctx.canAdmin || ctx.isOwner)) {
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
