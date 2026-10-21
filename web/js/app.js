// Shell: sign-in, project switcher, header with project state and the
// owner's absence, navigation, hash router. Each view is a function
// (ctx, root, args) registered in Maity.views; see views.md in context/
// for the order.
//
// Routes:
//   #/all                         everything waiting for the human, all projects
//   #/p/<slug>/<view>[/<arg>...]  a view inside one project
//   (empty)                       #/all with several projects, else the inbox
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const NAV = [
    { route: "inbox", label: "Inbox" },
    { route: "board", label: "Board" },
    { route: "agents", label: "Agents" },
    { route: "org", label: "Organisation" },
    { route: "chat", label: "Chat" },
    { route: "join", label: "Join an agent", admin: true },
  ];

  const STATES = ["build", "freeze", "fixes-only", "accepted", "archived"];
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
    const status = err.status ? "HTTP " + err.status + (err.code ? " " + err.code : "") + ": " : "";
    return h("div", { class: "error", role: "alert" },
      h("strong", null, "Could not load" + where),
      h("p", null, status + err.message),
      M.api.source === "api"
        ? h("p", null, "The page does not fall back to fixtures on its own. ",
          h("a", { href: "?source=fixtures" + window.location.hash }, "Open with fixtures"),
          " to look at sample data instead.")
        : null);
  }

  // The status line of a form: "Saving…", then nothing or the error.
  function statusLine() {
    const el = h("p", { class: "send-status", role: "status" });
    return {
      el,
      busy: (text) => { el.textContent = text; el.className = "send-status"; },
      done: () => { el.textContent = ""; el.className = "send-status"; },
      fail: (prefix, err) => { el.textContent = prefix + err.message; el.className = "send-status failed"; },
    };
  }

  function stateBadge(state, note) {
    return h("span", { class: "state state-" + state, title: note || "" }, STATE_LABELS[state] || state);
  }

  // ---- sign-in ------------------------------------------------------------

  function renderLogin(main) {
    append(clear(document.getElementById("header")), h("div", { class: "bar" },
      h("span", { class: "brand" }, "Maity"),
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null));
    const handle = h("input", { id: "login-handle", name: "handle", autocomplete: "username", required: true });
    const password = h("input", { id: "login-password", name: "password", type: "password", autocomplete: "current-password", required: true });
    const status = statusLine();
    const form = h("form", {
      class: "login",
      onsubmit: async (e) => {
        e.preventDefault();
        status.busy("Signing in…");
        try {
          await M.api.post("/auth/login", { handle: handle.value.trim(), password: password.value });
          password.value = "";
          render();
        } catch (err) {
          password.value = "";
          status.fail("Not signed in: ", err);
        }
      },
    },
    h("h2", null, "Sign in"),
    h("label", { for: "login-handle" }, "Handle"), handle,
    h("label", { for: "login-password" }, "Password"), password,
    h("button", { type: "submit" }, "Sign in"),
    status.el);
    append(clear(main), form);
  }

  async function logout() {
    try {
      await M.api.post("/auth/logout");
    } finally {
      window.location.hash = "";
      render();
    }
  }

  // ---- project state and absence ----------------------------------------

  // State (owner and admin, with a reason) and absence (owner only), as
  // PATCH /projects/{slug}.
  function projectPanel(ctx) {
    const status = statusLine();
    const save = async (body, label) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base, body);
        render();
      } catch (err) {
        status.fail(label + " not saved: ", err);
      }
    };

    const panel = h("div", { class: "panel", id: "project-panel" });
    if (ctx.canAdmin) {
      const state = h("select", { id: "state-select" },
        STATES.map((s) => h("option", { value: s, selected: s === ctx.project.state }, STATE_LABELS[s])));
      const note = h("input", { id: "state-note", value: ctx.project.state_note || "", placeholder: "What this state means right now" });
      const reason = h("input", { id: "state-reason", required: true, placeholder: "Why it changes (logged)" });
      append(panel, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          if (!reason.value.trim()) { reason.focus(); return; }
          save({ state: state.value, state_note: note.value.trim() || null, reason: reason.value.trim() }, "State");
        },
      },
      h("h3", null, "Project state"),
      h("label", { for: "state-select" }, "State"), state,
      h("label", { for: "state-note" }, "Note"), note,
      h("label", { for: "state-reason" }, "Reason"), reason,
      h("button", { type: "submit" }, "Change state")));
    }
    if (ctx.isOwner) {
      const a = ctx.project.absence;
      const until = h("input", { id: "absence-until", type: "datetime-local", required: true });
      const scope = h("input", { id: "absence-scope", required: true, placeholder: "What the admin roles may decide meanwhile", value: a ? a.scope : "" });
      append(panel, h("form", {
        class: "inline-form",
        onsubmit: (e) => {
          e.preventDefault();
          const when = new Date(until.value);
          if (!until.value || Number.isNaN(when.getTime())) { until.focus(); return; }
          if (!scope.value.trim()) { scope.focus(); return; }
          save({ absence: { until: when.toISOString().replace(/\.\d{3}Z$/, "Z"), scope: scope.value.trim() } }, "Absence");
        },
      },
      h("h3", null, "Your absence"),
      h("label", { for: "absence-until" }, "Away until"), until,
      h("label", { for: "absence-scope" }, "Meanwhile"), scope,
      h("button", { type: "submit" }, a ? "Update absence" : "Set absence"),
      a ? h("button", { type: "button", onclick: () => save({ absence: null }, "Absence") }, "I am back") : null));
    }
    append(panel, status.el);
    return panel;
  }

  // ---- header -------------------------------------------------------------

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
    const absence = ctx.scope === "project" ? ctx.project.absence : null;
    let panelOpen = false;
    const panelSlot = h("div");
    const toggle = ctx.scope === "project" && (ctx.canAdmin || ctx.isOwner)
      ? h("button", {
        type: "button",
        class: "small",
        "aria-expanded": "false",
        "aria-controls": "project-panel",
        onclick: (e) => {
          panelOpen = !panelOpen;
          e.target.setAttribute("aria-expanded", String(panelOpen));
          clear(panelSlot);
          if (panelOpen) append(panelSlot, projectPanel(ctx));
        },
      }, "State & absence")
      : null;
    append(header,
      h("div", { class: "bar" },
        h("span", { class: "brand" }, "Maity"),
        ctx.scope === "project"
          ? [h("span", { class: "project" }, ctx.project.name), stateBadge(ctx.project.state, ctx.project.state_note), toggle]
          : h("span", { class: "project" }, "Everything waiting for you"),
        M.api.source === "fixtures"
          ? h("span", { class: "source", title: "Data from web/fixtures/, not from the hub. Changes are kept in this tab only." }, "Fixtures")
          : null,
        h("span", { class: "me" }, ctx.me.display_name,
          h("button", { type: "button", class: "small", onclick: logout }, "Sign out"))),
      switcher(ctx),
      ctx.scope === "project" && ctx.project.state_note ? h("p", { class: "state-note" }, ctx.project.state_note) : null,
      absence
        ? h("p", { class: "flag absence" }, "Away until " + formatTime(absence.until) + " — " + absence.scope)
        : null,
      panelSlot,
      ctx.scope === "project"
        ? h("nav", { class: "views", "aria-label": "Views" },
          NAV.filter((item) => !item.admin || ctx.canAdmin).map((item) => h("a", {
            href: projectLink(ctx.slug, item.route),
            "aria-current": item.route === current ? "page" : null,
          }, item.label)))
        : null);
  }

  // ---- context ------------------------------------------------------------

  function withMembers(ctx, members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    ctx.members = members;
    ctx.memberById = byId;
    ctx.nameOf = (id) => (byId[id] ? byId[id].display_name : id || "—");
    return ctx;
  }

  async function loadContext(where, me) {
    const ctx = {
      me: me.member,
      projects: me.projects,
      serverTime: me.server_time,
      scope: where.scope,
      projectLink,
      stateLabel: (state) => STATE_LABELS[state] || state,
      refresh: render,
      // After an answer: re-read /me for the switcher's counts.
      refreshCounts: async () => {
        const fresh = await M.api.get("/me");
        ctx.projects = fresh.projects;
        renderHeader(ctx, where.route);
      },
    };
    if (where.scope !== "project") return ctx;
    const mine = me.projects.find((p) => p.slug === where.slug);
    if (!mine) {
      throw new M.api.ApiError("You are not a member of the project " + where.slug, 404, "/me", "not_found");
    }
    ctx.slug = where.slug;
    ctx.role = mine.role;
    // A human's owner and admin memberships hold project:admin and
    // members:admin (docs/api.md §2.3); absence is the owner's alone.
    ctx.canAdmin = mine.role === "owner" || mine.role === "admin";
    ctx.isOwner = mine.role === "owner";
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
      try {
        await M.api.get("/auth/session");
      } catch (err) {
        if (err.status === 401) {
          if (seq === renderSeq) renderLogin(main);
          return;
        }
        throw err;
      }
      const me = await M.api.get("/me");
      if (seq !== renderSeq) return;
      if (where.scope === null) {
        if (!me.projects.length) {
          throw new M.api.ApiError("You are not a member of any project yet", 0, "/me");
        }
        window.location.replace(me.projects.length > 1 ? "#/all" : projectLink(me.projects[0].slug, "inbox"));
        return;
      }
      ctx = await loadContext(where, me);
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
      const item = NAV.find((n) => n.route === where.route);
      if (where.scope === "all") {
        await M.views.inbox(ctx, root, []);
      } else if (where.scope === "project" && M.views[where.route] && !(item && item.admin && !ctx.canAdmin)) {
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
  M.statusLine = statusLine;
  M.STATE_LABELS = STATE_LABELS;

  window.addEventListener("hashchange", render);
  document.addEventListener("DOMContentLoaded", render);
})(window.Maity);
