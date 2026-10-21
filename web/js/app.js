// Shell: header with project state, navigation, hash router. Each view is
// a function (ctx, root) registered in Maity.views; see views.md in
// context/ for the order.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, clear } = M.dom;

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

  function parseHash() {
    const parts = window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
    return { route: parts[0] || "inbox", args: parts.slice(1).map(decodeURIComponent) };
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

  function renderHeader(ctx, current) {
    const header = clear(document.getElementById("header"));
    const state = ctx.project.state;
    header.append(
      h("div", { class: "bar" },
        h("span", { class: "brand" }, "Maity"),
        h("span", { class: "project" }, ctx.project.name),
        h("span", { class: "state state-" + state, title: ctx.project.state_note || "" },
          STATE_LABELS[state] || state),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: "Data from web/fixtures/, not from the hub. Answers are kept in this tab only." }, "Fixtures")
          : null),
      ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      h("nav", { "aria-label": "Views" },
        NAV.map((item) => h("a", {
          href: "#/" + item.route,
          "aria-current": item.route === current ? "page" : null,
        }, item.label,
        item.route === "inbox" && ctx.openRequests
          ? h("span", { class: "count", "aria-label": ctx.openRequests + " open" }, String(ctx.openRequests))
          : null))));
  }

  async function loadContext() {
    const me = await M.api.get("/me");
    const slug = me.projects[0] && me.projects[0].slug;
    if (!slug) throw new M.api.ApiError("No project for this member", 0, "/me");
    const [project, members, requests] = await Promise.all([
      M.api.get("/projects/" + slug),
      M.api.get("/projects/" + slug + "/members"),
      M.api.get("/projects/" + slug + "/requests"),
    ]);
    const byId = {};
    members.items.forEach((m) => { byId[m.id] = m; });
    return {
      me: me.member,
      slug,
      base: "/projects/" + slug,
      project,
      members: members.items,
      memberById: byId,
      nameOf: (id) => (byId[id] ? byId[id].display_name : id || "—"),
      openRequests: requests.items.filter((r) => r.status === "open").length,
      refresh: render,
    };
  }

  let renderSeq = 0;

  async function render() {
    const seq = ++renderSeq;
    const { route, args } = parseHash();
    const main = document.getElementById("main");
    let ctx;
    try {
      ctx = await loadContext();
    } catch (err) {
      if (seq !== renderSeq) return;
      clear(document.getElementById("header")).append(h("div", { class: "bar" }, h("span", { class: "brand" }, "Maity")));
      clear(main).append(errorBox(err));
      return;
    }
    if (seq !== renderSeq) return;
    renderHeader(ctx, route);
    const view = M.views[route];
    const root = h("section", { class: "view view-" + route });
    try {
      if (!view) {
        root.append(h("p", null, "Unknown view. ", h("a", { href: "#/inbox" }, "Go to the inbox.")));
      } else {
        await view(ctx, root, args);
      }
    } catch (err) {
      if (seq !== renderSeq) return;
      clear(root).append(errorBox(err));
    }
    if (seq !== renderSeq) return;
    clear(main).append(root);
    document.title = (NAV.find((n) => n.route === route) || { label: "Maity" }).label + " · " + ctx.project.name;
  }

  M.errorBox = errorBox;
  M.STATE_LABELS = STATE_LABELS;

  window.addEventListener("hashchange", render);
  document.addEventListener("DOMContentLoaded", render);
})(window.Maity);
