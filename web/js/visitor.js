// A public project as a reader who is no member sees it (docs/api.md §16.9, tsk-jj1tfre7n6zb):
// the views a member has, read-only, drawn only from GET /public/pages/{path}. Nothing here
// writes, polls or reads another route. A card here has no form and no actions, so it is drawn
// from the board's classes and not with board.js, whose card needs a member's context; its id
// links to its own page, `<owner>/<slug>/tasks/<id>`, where the hub stores the text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, safeUrl } = M.dom;

  const VIEWS = [
    { path: "", get label() { return M.t("nav.overview"); } },
    { path: "/board", get label() { return M.t("nav.board"); } },
    { path: "/members", get label() { return M.t("nav.members"); } },
    { path: "/organisation", get label() { return M.t("nav.organisation"); } },
    { path: "/why", get label() { return M.t("nav.why"); } },
  ];
  const PROJECT_KINDS = ["project", "board", "members", "organisation", "why", "card"];
  const COUNTERS = {
    get cards_done() { return M.t("visitor.stat.cards_done"); },
    get reviews_given() { return M.t("visitor.stat.reviews_given"); },
    get prs_merged() { return M.t("visitor.stat.prs_merged"); },
    get handovers() { return M.t("visitor.stat.handovers"); },
  };
  const NOTE_STATES = {
    get incorporated() { return M.t("visitor.note.incorporated"); },
    get dismissed() { return M.t("visitor.note.dismissed"); },
  };
  const COLUMNS = {
    get proposed() { return M.t("cards.column.proposed"); },
    get open() { return M.t("cards.column.open"); },
    get in_progress() { return M.t("cards.column.in_progress"); },
    get blocked() { return M.t("cards.column.blocked"); },
    get review() { return M.t("cards.column.review"); },
    get done() { return M.t("cards.column.done"); },
    get cancelled() { return M.t("cards.column.cancelled"); },
  };

  // A person's name as a link to their page; the path comes from the hub, the check stays here.
  function who(person) {
    return M.route.isRoute(person.page) ? h("a", { href: person.page }, person.name) : h("span", null, person.name);
  }
  const external = (url, label) => {
    const safe = safeUrl(url);
    return safe ? h("a", { href: safe, rel: "nofollow ugc" }, label || url) : null;
  };
  const names = (people) => h("ul", null, people.map((p) => h("li", null, who(p), " (" + p.handle + ")")));
  const projectList = (projects) => h("ul", null, projects.map((p) => h("li", null, h("a", { href: "/" + p.full_name }, p.name))));

  function statistics(totals) {
    return h("ul", { class: "visitor-stats" }, Object.keys(COUNTERS).filter((key) => totals[key] !== null && totals[key] !== undefined)
      .map((key) => h("li", null, COUNTERS[key] + ": " + totals[key])));
  }

  function editMark(e) {
    const o = { who: holderLabel(e.by) || M.t("visitor.holder.member"), at: M.dom.formatTime(e.at) };
    return e.reason ? M.tn("visitor.note.edited_reason", Object.assign(o, { reason: e.reason })) : M.tn("visitor.note.edited", o);
  }

  function holderLabel(holder) {
    if (!holder) return null;
    if (holder === "member") return h("span", { class: "muted" }, M.t("visitor.holder.member"));
    if (holder === "agent") return h("span", { class: "muted" }, M.t("visitor.holder.agent"));
    return who(holder);
  }

  const draw = {
    project(d) {
      return [
        h("p", { class: "muted" }, M.dom.word("project", d.state)),
        d.about ? h("div", { class: "about" }, M.markdown(d.about)) : null,
        d.repository_url ? h("p", null, external(d.repository_url)) : null,
        d.links.map((url) => h("p", null, external(url))),
        d.people.length ? [h("h2", null, M.t("visitor.people")), names(d.people)] : null,
        d.agents.length ? [h("h2", null, M.t("visitor.agents")), names(d.agents)] : null,
        d.ticker && d.ticker.length ? [h("h2", null, M.t("visitor.recently")), h("ul", { class: "visitor-ticker" }, d.ticker.map((e) => h("li", null,
          h("span", { class: "muted" }, M.dom.formatTime(e.at)), " ", (e.url && external(e.url, e.text)) || e.text)))] : null,
        d.online ? [h("h2", null, M.t("visitor.online")),
          h("p", null, M.t("visitor.online.humans", { count: d.online.humans }), " · ", M.t("visitor.online.agents", { count: d.online.agents })),
          d.online.named.length ? names(d.online.named) : null] : null,
        h("h2", null, M.t("visitor.statistics")), statistics(d.statistics.totals),
      ];
    },
    board(d, base) {
      return h("div", { class: "columns" }, d.columns.map((col) => h("section", { class: "column", "data-status": col.status, "aria-label": COLUMNS[col.status] || col.status },
        h("h2", null, (COLUMNS[col.status] || col.status) + " (" + col.cards.length + ")"),
        col.cards.map((c) => h("article", { class: "card", "data-card": c.id, "aria-label": c.title },
          h("header", null, h("a", { class: "card-id", href: base + "/tasks/" + c.id }, c.id), c.label ? h("span", { class: "label-tag" }, M.dom.word("label", c.label)) : null),
          h("h3", null, c.title),
          holderLabel(c.holder))))));
    },
    card(d) {
      return [
        h("p", null, h("span", { class: "card-id" }, d.id), " ", h("span", { class: "label-tag" }, COLUMNS[d.status] || d.status),
          d.label ? [" ", h("span", { class: "label-tag" }, M.dom.word("label", d.label))] : null,
          d.holder ? [" ", holderLabel(d.holder)] : null),
        d.body && d.body.trim() ? h("div", { class: "about" }, M.markdown(d.body)) : null,
        d.notes && d.notes.length ? [h("h2", null, M.t("cardpanel.notes")), h("ol", { class: "card-notes" }, d.notes.map((n) => h("li", { "data-note": n.id },
          h("p", { class: "muted" }, holderLabel(n.author), " · ", M.dom.formatTime(n.created_at), NOTE_STATES[n.state] ? " · " + NOTE_STATES[n.state] : "",
            // The edit mark as the hub's own page has it (§16.9, a card's page): the editor named as a holder, the date,
            // the reason; never the old text, and none on a removed note.
            n.edited && !n.redacted ? [" · ", editMark(n.edited)] : null),
          n.redacted ? h("p", { class: "muted" }, M.t("jfa.redacted")) : h("div", { class: "about" }, M.markdown(n.body || "")))))] : null,
      ];
    },
    members(d) {
      return [
        h("ul", null, d.shown.map((p) => h("li", null, who(p), " (" + p.handle + ") ", h("span", { class: "muted" }, M.trust.roleLabel(p.role))))),
        d.others.length ? [h("h2", null, M.t("visitor.others")),
          h("ul", null, d.others.map((o) => h("li", null, o.count + " × " + M.trust.roleLabel(o.role))))] : null,
      ];
    },
    organisation(d) {
      const below = (index) => d.nodes.filter((n) => n.reports_to === index);
      // A line back to a node already drawn is not followed: the answer is data, not a promise.
      const node = (n, seen) => h("li", null, n.person ? who(n.person) : h("span", { class: "muted" }, M.trust.roleLabel(n.role)),
        n.person ? h("span", { class: "muted" }, " " + M.trust.roleLabel(n.role)) : null,
        branch(below(n.index).filter((c) => !seen.has(c.index)), new Set([...seen, n.index])));
      const branch = (list, seen) => (list.length ? h("ul", null, list.map((n) => node(n, new Set([...seen, n.index])))) : null);
      return h("div", { class: "org-box" }, branch(below(null), new Set()));
    },
    why(d) {
      if (!d.readable) return h("p", { class: "muted" }, M.t("visitor.why.unread"));
      return [
        h("p", null, M.t("visitor.why.entries", { count: d.summary.entries })),
        d.family.length ? [h("h2", null, M.t("visitor.why.family")),
          h("ul", null, d.family.map((m) => h("li", null, external(m.dashboard_url, m.name || m.path) || (m.name || m.path))))] : null,
        d.attention.length ? [h("h2", null, M.t("visitor.why.attention")),
          h("ul", null, d.attention.map((a) => h("li", null, external(a.link, a.title) || a.title, " ", h("span", { class: "label-tag" }, M.why.statusWord(a.status)))))] : null,
      ];
    },
    person(d) {
      return [
        d.bio ? h("p", null, d.bio) : null,
        d.website ? h("p", null, external(d.website)) : null,
        d.social ? h("ul", null, Object.keys(d.social).map((net) => h("li", null, net + ": " + d.social[net]))) : null,
        d.projects.length ? [h("h2", null, M.t("visitor.projects")), projectList(d.projects)] : null,
        d.agents.length ? [h("h2", null, M.t("visitor.agents")), names(d.agents)] : null,
      ];
    },
    agent(d) {
      return [
        h("p", null, who(d.owner)),
        h("h2", null, M.t("visitor.projects")), projectList(d.projects),
        h("h2", null, M.t("visitor.statistics")), statistics(d.statistics),
      ];
    },
    organisation_page(d) {
      return d.projects.length ? [h("h2", null, M.t("visitor.projects")), projectList(d.projects)] : null;
    },
  };

  // The project's address under which a view of it stands: `<owner>/<slug>`.
  const projectBase = (path) => "/" + path.split("/").filter(Boolean).slice(0, 2).join("/");

  // Whether the address can name a stored page at all: the hub is not asked for the rest.
  function canBePublic(where, path) {
    const parts = path.split("/").filter(Boolean);
    if (where.scope === "person") return parts.length === 1;
    if (where.scope !== "project") return false;
    if (parts[1] === "agents") return parts.length === 3;
    if (parts[2] === "tasks") return parts.length === 4;
    if (parts[2] === "overview") return parts.length === 3 || (parts.length === 4 && ["project", "swarm"].includes(parts[3]));
    return parts.length === 2 || (parts.length === 3 && ["board", "members", "organisation", "why"].includes(parts[2]));
  }

  // The member Overview's addresses (§16.11) read the project's own page, the public overview
  // (§16.9, the maintainer's decision of 2026-11-01): the badge links to /overview (§6.20). Its swarm
  // tab is the members' alone; null there, where the caller decides. An agent's page is its own:
  // `overview` is a handle an agent may hold (hub/src/maity_hub/paths.py, `handle_reserved`).
  function storedPath(path) {
    const parts = path.split("/").filter(Boolean);
    if (parts[1] === "agents" || parts[2] !== "overview") return path;
    return parts[3] === "swarm" ? null : "/" + parts.slice(0, 2).join("/");
  }

  // Draws the page of `path` when the hub stores one; false when it stores none, for the
  // caller's own answer (the login, or not_found).
  async function page(main, header, where, path, { signedIn, brand, tools, head, live }) {
    if (!canBePublic(where, path)) return false;
    const stored = storedPath(path);
    if (stored === null) {
      // The swarm: a visitor keeps the login, which goes on here after the sign-in (§16.11); a
      // signed-in non-member is taken to the overview instead of being told they are none, but
      // only where the project has a page: an earlier address (a rename, a transfer) has none, and
      // the caller then leads a member on to the current one, the tab kept.
      if (!signedIn) return false;
      try {
        await M.api.get("/public/pages/" + path.split("/").filter(Boolean).slice(0, 2).join("/"));
      } catch (err) {
        if (err.status === 404) return false;
        throw err;
      }
      if (live()) M.route.go(path.replace(/\/swarm\/?$/, ""), { replace: true });
      return true;
    }
    let answer;
    try {
      answer = await M.api.get("/public/pages/" + stored.replace(/^\/+/, ""));
    } catch (err) {
      // No page: the caller's answer stands. Signed out, so does a failed read: the login is
      // still a way on. Signed in, it is said as any failed page is.
      if (err.status === 404 || !signedIn) return false;
      throw err;
    }
    if (!live()) return true;
    const d = answer.data;
    const inProject = PROJECT_KINDS.includes(answer.kind);
    const base = inProject ? projectBase(answer.path) : answer.path;
    if (signedIn) {
      await head();
      if (!live()) return true;
    } else {
      const signIn = h("a", { class: "visitor-sign-in", href: M.withNext("/login", path) }, M.t("visitor.sign_in"));
      append(clear(header), h("div", { class: "bar" }, brand, signIn, tools));
    }
    const title = answer.kind === "card" ? d.title : d.name || base.slice(1);
    append(clear(main), h("section", { class: "view-visitor", "data-kind": answer.kind },
      h("h1", null, title),
      inProject ? h("nav", { class: "view-tabs", "aria-label": title }, VIEWS.map((v) => h("a", {
        href: base + v.path,
        class: "view-tab",
        // A card's page belongs to the Board, the tab it is reached from.
        "aria-current": base + v.path === answer.path || (answer.kind === "card" && v.path === "/board") ? "page" : null,
      }, v.label))) : null,
      draw[answer.kind] ? draw[answer.kind](d, base) : null));
    document.title = title;
    return true;
  }

  M.visitor = { page };
})(window.Maity);
