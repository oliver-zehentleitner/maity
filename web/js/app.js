// Shell: project switcher, header with project state, navigation, hash
// router. Each view is a function (ctx, root, args) registered in
// Maity.views; see views.md in context/ for the order.
//
// Routes:
//   #/all                         everything waiting for the human, all projects
//   #/p/<slug>/<view>[/<arg>...]  a view inside one project
//   (empty)                       #/all with several projects, else the inbox
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const NAV = [
    { route: "inbox", label: "Inbox" },
    { route: "board", label: "Board" },
    { route: "agents", label: "Agents" },
    { route: "org", label: "Organisation" },
    { route: "chat", label: "Chat" },
  ];

  const STATE_LABELS = {
    build: "Build",
    freeze: "Freeze",
    "fixes-only": "Fixes only",
    accepted: "Accepted",
    archived: "Archived",
  };

  M.views = M.views || {};

  function projectLink(slug, view, ...rest) {
    return "#/p/" + [slug, view].concat(rest).map(encodeURIComponent).join("/");
  }

  function parseHash() {
    const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
    if (!parts.length) return { scope: null };
    if (parts[0] === "all") return { scope: "all" };
    if (parts[0] === "p" && parts[1]) {
      return { scope: "project", slug: parts[1], route: parts[2] || "inbox", args: parts.slice(3) };
    }
    return { scope: "unknown" };
  }

  function errorBox(err) {
    const where = err.path ? " (" + err.path + ")" : "";
    const status = err.status ? "HTTP " + err.status + ": " : "";
    return h("div", { class: "error", role: "alert" },
      h("strong", null, "Could not load" + where),
      h("p", null, status + err.message),
      M.api.source === "api"
        ? h("p", null, "The page does not fall back to fixtures on its own. ",
          h("a", { href: "?source=fixtures" + window.location.hash }, "Open with fixtures"),
          " to look at sample data instead.")
        : null);
  }

  function stateBadge(state, note) {
    return h("span", { class: "state state-" + state, title: note || "" }, STATE_LABELS[state] || state);
  }

  // Always visible: every project of this human with what waits there, and
  // the cross-project view with the total.
  function switcher(ctx) {
    const total = ctx.projects.reduce((n, p) => n + (p.open_requests || 0), 0);
    const count = (n) => (n ? h("span", { class: "count", "aria-label": n + " open" }, String(n)) : null);
    return h("nav", { class: "switcher", "aria-label": "Projects" },
      h("a", { href: "#/all", "aria-current": ctx.scope === "all" ? "page" : null }, "All projects", count(total)),
      ctx.projects.map((p) => h("a", {
        href: projectLink(p.slug, "inbox"),
        "aria-current": ctx.scope === "project" && p.slug === ctx.slug ? "page" : null,
      },
      p.name,
      h("span", { class: "dot state-dot-" + p.state, title: STATE_LABELS[p.state] || p.state, "aria-label": STATE_LABELS[p.state] || p.state }),
      count(p.open_requests))));
  }

  function renderHeader(ctx, current) {
    const header = clear(document.getElementById("header"));
    append(header,
      h("div", { class: "bar" },
        h("span", { class: "brand" }, "Maity"),
        ctx.scope === "project"
          ? [h("span", { class: "project" }, ctx.project.name), stateBadge(ctx.project.state, ctx.project.state_note)]
          : h("span", { class: "project" }, "Everything waiting for you"),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: "Data from web/fixtures/, not from the hub. Answers are kept in this tab only." }, "Fixtures")
          : null),
      switcher(ctx),
      ctx.scope === "project" && ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      ctx.scope === "project"
        ? h("nav", { class: "views", "aria-label": "Views" },
          NAV.map((item) => h("a", {
            href: projectLink(ctx.slug, item.route),
            "aria-current": item.route === current ? "page" : null,
          }, item.label)))
        : null);
  }

  function withMembers(ctx, members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    ctx.members = members;
    ctx.memberById = byId;
    ctx.nameOf = (id) => (byId[id] ? byId[id].display_name : id || "—");
    return ctx;
  }

  async function loadContext(where) {
    const me = await M.api.get("/me");
    const ctx = {
      me: me.member,
      projects: me.projects,
      scope: where.scope,
      projectLink,
      stateLabel: (state) => STATE_LABELS[state] || state,
      refresh: render,
      // After an answer: keep the switcher's counts current without a reload.
      adjustOpen: (slug, delta) => {
        const p = ctx.projects.find((x) => x.slug === slug);
        if (p) p.open_requests = Math.max(0, (p.open_requests || 0) + delta);
        renderHeader(ctx, where.route);
      },
    };
    if (where.scope !== "project") return ctx;
    if (!me.projects.some((p) => p.slug === where.slug)) {
      throw new M.api.ApiError("You are not a member of the project " + where.slug, 404, "/me");
    }
    ctx.slug = where.slug;
    ctx.base = "/projects/" + encodeURIComponent(where.slug);
    ctx.link = (view, ...rest) => projectLink(where.slug, view, ...rest);
    const [project, members] = await Promise.all([
      M.api.get(ctx.base),
      M.api.get(ctx.base + "/members"),
    ]);
    ctx.project = project;
    return withMembers(ctx, members.items);
  }

  let renderSeq = 0;

  async function render() {
    const seq = ++renderSeq;
    const where = parseHash();
    const main = document.getElementById("main");
    let ctx;
    try {
      if (where.scope === null) {
        const me = await M.api.get("/me");
        if (seq !== renderSeq) return;
        if (!me.projects.length) {
          throw new M.api.ApiError("You are not a member of any project yet", 0, "/me");
        }
        window.location.replace(me.projects.length > 1 ? "#/all" : projectLink(me.projects[0].slug, "inbox"));
        return;
      }
      ctx = await loadContext(where);
    } catch (err) {
      if (seq !== renderSeq) return;
      append(clear(document.getElementById("header")), h("div", { class: "bar" }, h("span", { class: "brand" }, "Maity")));
      append(clear(main), errorBox(err));
      return;
    }
    if (seq !== renderSeq) return;
    renderHeader(ctx, where.route);
    const root = h("section", { class: "view view-" + (where.scope === "all" ? "all" : where.route) });
    try {
      if (where.scope === "all") {
        await M.views.inbox(ctx, root, []);
      } else if (where.scope === "project" && M.views[where.route]) {
        await M.views[where.route](ctx, root, where.args);
      } else {
        append(root, h("p", null, "Unknown view. ", h("a", { href: "#/all" }, "Go to everything waiting for you.")));
      }
    } catch (err) {
      if (seq !== renderSeq) return;
      append(clear(root), errorBox(err));
    }
    if (seq !== renderSeq) return;
    append(clear(main), root);
    const label = where.scope === "all"
      ? "All projects"
      : (NAV.find((n) => n.route === where.route) || { label: "Maity" }).label + " · " + (ctx.project ? ctx.project.name : "");
    document.title = label + " · Maity";
  }

  M.errorBox = errorBox;
  M.STATE_LABELS = STATE_LABELS;

  window.addEventListener("hashchange", render);
  document.addEventListener("DOMContentLoaded", render);
})(window.Maity);
