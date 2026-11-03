// The project's Why view hosts Keep the Why's own views (timeline, graph, family, search,
// thoughts, pages): the library vendored in vendor/keep-the-why/ (context/stack.md), loaded
// on the first visit to Why, given a provider over the hub's §11.5 reads, the dashboard's
// paths as its navigation, the browser's storage as its settings and Maity's colours as its
// tokens (css/app.css). Its UI words are English for now and marked translate="no"
// (context/views.md); entry text is the repository's and rendered as text by the library.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // The library's files in its manifest's order (vendor/keep-the-why/ktw-views.json);
  // tools/check.py fails when they differ.
  const DIR = "vendor/keep-the-why/";
  const SCRIPTS = ["ktw-core.js", "ktw-ui.js", "ktw-scene.js", "ktw-markdown.js", "ktw-graph.js", "ktw-timeline.js",
    "ktw-family.js", "ktw-search.js", "ktw-thoughts.js", "ktw-pages.js"];
  const STYLES = ["ktw-views.css"];
  // The places offered in the view's own row of links; the library links to the others.
  const PLACES = {
    overview: () => M.t("why.lib.place.overview"), graph: () => M.t("why.lib.place.graph"),
    timeline: () => M.t("why.lib.place.timeline"), thoughts: () => M.t("why.lib.place.thoughts"),
    family: () => M.t("why.lib.place.family"),
  };

  // --- loading: once per page, on the first visit to Why ------------------------------------

  // Loaded only when every file is: a file that failed leaves the library incomplete, and the
  // next visit appends just the files still missing (the stylesheet once).
  let loading = null;
  let ready = false;
  let styled = false;
  const done = new Set();
  function load() {
    if (ready) return Promise.resolve(window.KeepTheWhy);
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      if (!styled) {
        for (const name of STYLES) append(document.head, h("link", { rel: "stylesheet", href: DIR + name }));
        styled = true;
      }
      // In order, one after the other: each file uses the ones before it.
      const next = (i) => {
        if (i < SCRIPTS.length && done.has(SCRIPTS[i])) { next(i + 1); return; }
        if (i >= SCRIPTS.length) {
          loading = null;
          if (window.KeepTheWhy && window.KeepTheWhy.views && window.KeepTheWhy.views.pages) {
            ready = true;
            resolve(window.KeepTheWhy);
          } else {
            // loaded but not complete (a file that threw as it ran): the last file is tried again
            done.delete(SCRIPTS[SCRIPTS.length - 1]);
            reject(new Error(M.t("why.lib.not_loaded")));
          }
          return;
        }
        const s = h("script", { src: DIR + SCRIPTS[i],
          onload: () => { done.add(SCRIPTS[i]); next(i + 1); },
          onerror: () => { s.remove(); loading = null; reject(new Error(M.t("why.lib.not_loaded"))); } });
        append(document.head, s);
      };
      next(0);
    });
    return loading;
  }

  // --- the provider: §11.5 through M.api ------------------------------------------------------

  // A refusal in Maity's words, as the library shows it beside what it could not read.
  function failure(err) {
    const reason = err && err.details && err.details.reason;
    if (err && err.code === "probe_unavailable") {
      const at = err.details && err.details.retry_at;
      return at ? M.t("why.lib.error.budget_until", { time: M.dom.formatTime(at) }) : M.t("why.lib.error.budget");
    }
    if (err && err.code === "probe_not_configured") return M.t("why.lib.error.no_access");
    if (reason === "not_in_family") return M.t("why.lib.error.not_in_family");
    if (reason === "not_public") return M.t("why.lib.error.not_public");
    if (reason === "family_cap") return M.t("why.lib.error.family_cap");
    if (reason) return M.why.reasonText({ reason, status: err.details.status, version: err.details.version });
    return (err && err.message) || M.t("why.reason.unavailable");
  }

  // A link the library takes from an export is used only when plain https, as every link from
  // data in the dashboard (context/rendering.md): the project's canonical URL (which its file and
  // tree links start with), the config's canonical and dashboard-state, a git remote and the
  // repository it is a fork of (written after "https://"), a See into another repository and a
  // superseded_by in another one. Any other is dropped before the library sees it; a
  // superseded_by keeps its entry's id. Links in entry text are left to `guard` below.
  const SUPERSEDED_ELSEWHERE = /^(\S+)\s+[—–-]\s+([0-9a-f-]{36})\s+[—–-]/i;
  function dropUnsafe(obj, key, prefix = "") {
    if (obj && typeof obj === "object" && key in obj && !M.dom.safeUrl(prefix + obj[key])) delete obj[key];
  }
  function httpsOnly(raw) {
    const project = raw && raw.project && typeof raw.project === "object" ? raw.project : null;
    if (project) {
      dropUnsafe(project, "canonical");
      dropUnsafe(project.config, "canonical");
      dropUnsafe(project.config, "dashboard-state");
      if (project.git && typeof project.git.remote === "string") dropUnsafe(project.git, "remote", "https://");
      if (project.git && project.git.fork && typeof project.git.fork.of === "string") dropUnsafe(project.git.fork, "of", "https://");
    }
    for (const e of (raw && Array.isArray(raw.entries) ? raw.entries : [])) {
      for (const see of (e && Array.isArray(e.see) ? e.see : [])) dropUnsafe(see, "remote");
      const m = e && typeof e.superseded_by === "string" ? SUPERSEDED_ELSEWHERE.exec(e.superseded_by.trim()) : null;
      if (m && /^[a-z][a-z0-9+.-]*:/i.test(m[1]) && !M.dom.safeUrl(m[1])) e.superseded_by = m[2];
    }
    return raw;
  }

  // Every link the library writes into the view, entry text included, is held to the rule
  // dom.h holds Maity's own to: a path of the dashboard or plain https. Any other loses its
  // target before it can be followed (a MutationObserver runs before the next event).
  function linkOk(value) {
    if (typeof value !== "string") return false;
    if (M.dom.safeUrl(value)) return true;
    const path = M.route.fixture ? value.slice(1) : value; // fixture mode writes a route after "#"
    return M.route.isRoute(path) && M.route.href(path) === value;
  }
  function sweep(node) {
    const href = node.getAttribute ? node.getAttribute("href") : null;
    if (href != null && !linkOk(href)) node.removeAttribute("href");
    for (const child of node.childNodes || []) sweep(child);
  }
  function guard(mount) {
    if (typeof MutationObserver === "function") {
      new MutationObserver(() => sweep(mount)).observe(mount, { subtree: true, childList: true, attributes: true, attributeFilter: ["href"] });
    }
    return mount;
  }

  function provider(base) {
    const origin = new WeakMap(); // a state -> where it was read: its bodies are asked for there
    const query = (canonical, root) => {
      const q = new URLSearchParams();
      if (canonical) q.set("canonical", canonical);
      if (root) q.set("root", root);
      const s = q.toString();
      return s ? "?" + s : "";
    };
    async function exportState(canonical = "", root = "") {
      const read = (r) => {
        const state = window.KeepTheWhy.core.normalizeState(httpsOnly(r.state));
        origin.set(state, { canonical: canonical ? r.canonical : "", root: r.root });
        return { state, url: r.url, canonical: r.canonical, root: r.root, raw: null };
      };
      try {
        return read(await M.api.get(base + "/keep-the-why/export" + query(canonical, root)));
      } catch (err) {
        const last = err && err.code === "ktw_unavailable" && err.details && err.details.last;
        // the hub's last good read of it (§11.5), said as such beside it
        if (last && last.state) return Object.assign(read(last), { stale: failure(err), at: last.observed_at });
        return { error: failure(err), code: err && err.code, canonical, root, raw: null };
      }
    }
    return {
      state: () => exportState("", ""),
      exportState,
      async bodies(state) {
        const from = origin.get(state);
        if (!state || typeof state.bodies !== "string" || !from) return { state };
        try {
          const r = await M.api.get(base + "/keep-the-why/bodies" + query(from.canonical, from.root));
          for (const e of state.entries) {
            const b = Object.hasOwn(r.bodies, e.id) ? r.bodies[e.id] : null;
            if (b != null) e.body = b && typeof b === "object" ? b : { text: String(b), reason: "" };
          }
          state.bodiesLoaded = true;
          return { state, url: r.url };
        } catch (err) {
          return { state, error: failure(err) };
        }
      },
    };
  }

  // --- settings in the browser ------------------------------------------------------------------

  const prefs = {
    get(key, fallback) {
      try { const v = window.localStorage.getItem("maity-ktw-" + key); return v === null ? fallback : v; } catch (e) { return fallback; }
    },
    set(key, value) {
      try { window.localStorage.setItem("maity-ktw-" + key, String(value)); } catch (e) { /* storage blocked: kept for this view only */ }
    },
  };

  // --- one host per project, kept while the page is open --------------------------------------

  let host = null;

  // The path of Why in this project: /<owner>/<slug>/why, from the address's first two segments
  // (a project's address, app.js parseRoute), never by searching the text for "/why".
  function whyPath() {
    const parts = M.route.current().path.split("/").filter(Boolean);
    return "/" + parts.slice(0, 2).join("/") + "/why";
  }

  // The route of the path's segments below Why (decoded by app.js). A topic's file is taken as
  // it stands: the library's grammar writes and reads it unencoded.
  function routeOf(args) {
    const K = window.KeepTheWhy;
    if (!args || !args.length) return { view: "overview" };
    if (args[0] === "topic") return { view: "topic", file: args.slice(1).join("/") };
    return K.core.routes.parse("#" + args.map(encodeURIComponent).join("/").replace(/%2C/g, ","));
  }

  // The path below Why of a route. The library's grammar has no place for a route's `centre`
  // (another repository of the family): an entry there is its `ref` place, which reads that
  // repository's export through the family; any other place there is the family page, which
  // lists it. A topic's file is written segment by segment, encoded.
  function below(K, route) {
    let r = route;
    if (r && r.centre) {
      r = r.view === "entry" && r.centre.mode === "public" && r.centre.canonical
        ? { view: "ref", canonical: r.centre.canonical, uuid: r.uuid } : { view: "family" };
    }
    if (r && r.view === "topic") return "topic/" + String(r.file || "").split("/").map(encodeURIComponent).join("/");
    return K.core.routes.format(r).slice(1); // the format's leading hash dropped
  }

  async function makeHost(ctx) {
    const K = window.KeepTheWhy;
    const P = provider(ctx.base);
    const first = await P.state();
    if (first.error) return { error: first.error, code: first.code };
    const state = first.state;
    const stale = first.stale ? { reason: first.stale, at: first.at } : null;
    const prefix = whyPath();
    let current = { view: "overview" };
    const pathOf = (route) => prefix + "/" + below(K, route);
    const nav = {
      href: (route) => M.route.href(pathOf(route)),
      go(route, opts) { current = route; M.route.go(pathOf(route), { replace: !!(opts && opts.replace) }); },
      current: () => current,
    };
    const scene = K.scene.create({ state, self: state, scope: "project" });
    const family = K.views.family.create({ scene, nav, provider: () => P, host: { mode: () => "export", root: () => "" } });
    const search = K.views.search.create({ scene, nav, family });
    const thoughts = K.views.thoughts.create({ scene, nav, prefs });
    const pages = K.views.pages.create({ scene, nav, prefs, family, search });
    const graphView = K.views.graph.create({ scene, nav, prefs });
    const timeline = K.views.timeline.create({ scene, nav, prefs });
    let G = null;
    const graphOf = () => (G ||= Object.assign({ scale: 1, ox: 0, oy: 0, showEntries: true, showLabels: true, alpha: 1 },
      graphView.assemble(state.topics, state.entries)));
    return { K, P, state, stale, nav, scene, family, search, thoughts, pages, graphView, timeline, graphOf, slug: prefix,
      setRoute: (r) => { current = r; } };
  }

  function place(x, route, main, aside) {
    const { K, nav, pages, family, search, thoughts, graphView, timeline, graphOf } = x;
    const render = () => draw(x, route, main, aside);
    const topicHref = (file) => nav.href({ view: "topic", file });
    const H = {
      live: () => false, published: () => true, project: () => null, provider: () => x.P,
      inline: (md) => K.markdown.renderInline(document, md, { topicHref }),
      renderBody: (md) => K.markdown.render(document, md, { topicHref }),
      shareUrl: (r) => ({ url: new URL(x.slug + "/" + below(K, r), window.location.origin).href, where: "Maity" }),
      details: () => aside, miniGraph: () => {},
      entryThoughts: () => [], thoughts, memberLink: (m, href) => href,
      authorLink: (n) => document.createTextNode(n || "-"),
      authorProjects: () => [{ name: x.state.project.id || "", canonical: "", state: x.state, open: nav.href({ view: "authors" }), role: "self", anonymized: false }],
      friendsWaiting: () => [], friendsLoading: () => false, loadFriends: () => {},
      render, rerender: render,
    };
    const T = {
      graph: async () => graphOf(), light: (g, t) => graphView.lightThought(g, t),
      follow: { busy: () => false, chain: () => {}, all: () => {} },
      findEntry: (uuid) => {
        const e = x.state.entries.find((y) => y.uuid === uuid);
        return e ? { e, own: true, href: nav.href({ view: "entry", uuid }), origin: { state: x.state } } : null;
      },
      bodies: (st) => family.bodies(st), needFriends: () => {}, pick: () => false,
      inline: H.inline, renderBody: H.renderBody, listBox: () => aside, render,
    };
    const r = route;
    if (r.view === "graph") {
      const wrap = h("div", { class: "ktw-graph-wrap why-graph" });
      const canvas = h("canvas");
      append(wrap, canvas);
      append(main, wrap);
      graphView.run(canvas, graphOf(), { fit: true, onEntry: (n) => nav.go({ view: "entry", uuid: n.entry.uuid || n.entry.id }), onTopic: (n) => nav.go({ view: "topic", file: n.file }) });
    } else if (r.view === "timeline") timeline.view(main, r.day || null, { graph: () => graphOf(), bodies: (st) => family.bodies(st), entryRow: (e) => pages.entryRow(e, H), renderBody: H.renderBody, render });
    else if (r.view === "thoughts") thoughts.page(main, T);
    else if (r.view === "thought") thoughts.reader(main, r.refs, T);
    else if (r.view === "queues") pages.queuesPage(main, H);
    else if (r.view === "findings") pages.findings(main);
    else if (r.view === "authors") pages.authors(main, H);
    else if (r.view === "topic") pages.topic(main, r.file, H);
    else if (r.view === "entry") pages.entry(main, r.uuid, H);
    else if (r.view === "search") search.view(main, r.scope || "self", r.q || "");
    else if (r.view === "family") family.view(main);
    else if (r.view === "ref") {
      // the repository comes from the address: plain https or nothing is read (context/rendering.md)
      if (M.dom.safeUrl(r.canonical)) pages.remoteEntry(main, r.canonical, r.uuid, H);
      else append(main, h("p", { class: "flag" }, M.t("why.lib.error.not_in_family")));
    }
    else pages.overview(main, H);
  }

  function draw(x, route, main, aside) {
    clear(main);
    clear(aside);
    place(x, route, main, aside);
    sweep(main); // what the library wrote at once; `guard` takes what it writes later
    sweep(aside);
  }

  // Read again drops what this page holds of the project and reads its export anew.
  const readAgain = (ctx) => h("button", { type: "button", class: "small", onclick: () => { host = null; ctx.refresh(); } }, M.t("why.lib.read_again"));

  function toolbar(x, route, ctx) {
    const again = readAgain(ctx);
    return h("div", { class: "toolbar why-toolbar" },
      h("nav", { class: "why-places", "aria-label": M.t("why.lib.places") },
        Object.keys(PLACES).map((view) => h("a", { href: x.slug + (view === "overview" ? "" : "/" + view),
          "aria-current": route.view === view ? "page" : null }, PLACES[view]()))),
      again);
  }

  M.views.why = async function (ctx, root, args) {
    clear(root);
    const status = h("p", { class: "muted", role: "status" }, M.t("why.lib.loading"));
    append(root, status);
    try {
      await load();
    } catch (err) {
      append(clear(root), M.errorBox(err), readAgain(ctx));
      return;
    }
    // Kept per project and per reader: another project, or another person signed in in this
    // tab, reads anew.
    const key = ctx.base + "|" + ((ctx.me && ctx.me.id) || "");
    if (!host || host.key !== key) {
      host = null;
      const made = await makeHost(ctx);
      if (made.code === "ktw_not_configured") {
        append(clear(root), M.why.emptyState(ctx));
        return;
      }
      if (made.error) {
        append(clear(root), h("h2", null, M.t("why.title")), h("p", { class: "flag" }, made.error), readAgain(ctx));
        return;
      }
      host = Object.assign(made, { key });
    }
    const route = routeOf(args);
    host.setRoute(route);
    const main = guard(h("div", { class: "ktw-root why-main", translate: "no" }));
    const aside = guard(h("aside", { class: "ktw-root ktw-aside why-aside", translate: "no" }));
    const note = host.stale ? h("p", { class: "flag" }, M.t("why.lib.stale", { reason: host.stale.reason,
      ago: host.stale.at ? M.dom.formatAgo(host.stale.at) : "" })) : null;
    append(clear(root), toolbar(host, route, ctx), note, h("div", { class: "why-layout" }, main, aside));
    draw(host, route, main, aside);
  };

  M.ktwHost = { SCRIPTS, STYLES, routeOf, below, failure, provider, load, whyPath, httpsOnly, linkOk, sweep };
})(window.Maity);
