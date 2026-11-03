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

  let loading = null;
  function load() {
    if (window.KeepTheWhy) return Promise.resolve(window.KeepTheWhy);
    if (loading) return loading;
    loading = new Promise((resolve, reject) => {
      for (const name of STYLES) append(document.head, h("link", { rel: "stylesheet", href: DIR + name }));
      // In order, one after the other: each file uses the ones before it.
      const next = (i) => {
        if (i >= SCRIPTS.length) {
          if (window.KeepTheWhy) resolve(window.KeepTheWhy);
          else reject(new Error(M.t("why.lib.not_loaded")));
          return;
        }
        const s = h("script", { src: DIR + SCRIPTS[i], onload: () => next(i + 1),
          onerror: () => { loading = null; reject(new Error(M.t("why.lib.not_loaded"))); } });
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
    if (err && err.code === "probe_unavailable") return M.t("why.lib.error.budget");
    if (err && err.code === "probe_not_configured") return M.t("why.lib.error.no_access");
    if (reason === "not_in_family") return M.t("why.lib.error.not_in_family");
    if (reason === "not_public") return M.t("why.lib.error.not_public");
    if (reason === "family_cap") return M.t("why.lib.error.family_cap");
    if (reason) return M.why.reasonText({ reason, status: err.details.status, version: err.details.version });
    return (err && err.message) || M.t("why.reason.unavailable");
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
      try {
        const r = await M.api.get(base + "/keep-the-why/export" + query(canonical, root));
        const state = window.KeepTheWhy.core.normalizeState(r.state);
        origin.set(state, { canonical: canonical ? r.canonical : "", root: r.root });
        return { state, url: r.url, canonical: r.canonical, root: r.root, raw: null };
      } catch (err) {
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
            const b = r.bodies[e.id];
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

  // The path of Why in this project: what the address has up to and with /why.
  function whyPath() {
    const path = M.route.current().path;
    const at = path.indexOf("/why");
    return at < 0 ? path.replace(/\/$/, "") + "/why" : path.slice(0, at + 4);
  }

  function routeOf(args) {
    const K = window.KeepTheWhy;
    if (!args || !args.length) return { view: "overview" };
    return K.core.routes.parse("#" + args.map(encodeURIComponent).join("/").replace(/%2C/g, ","));
  }

  async function makeHost(ctx) {
    const K = window.KeepTheWhy;
    const P = provider(ctx.base);
    const first = await P.state();
    if (first.error) return { error: first.error, code: first.code };
    const state = first.state;
    const prefix = whyPath();
    let current = { view: "overview" };
    const pathOf = (route) => prefix + "/" + K.core.routes.format(route).slice(1); // the format's leading hash dropped
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
    return { K, P, state, nav, scene, family, search, thoughts, pages, graphView, timeline, graphOf, slug: prefix,
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
      shareUrl: (r) => ({ url: new URL(x.slug + "/" + K.core.routes.format(r).slice(1), window.location.origin).href, where: "Maity" }),
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
    } else if (r.centre) elsewhere(x, r, main);
    else if (r.view === "timeline") timeline.view(main, r.day || null, { graph: () => graphOf(), bodies: (st) => family.bodies(st), entryRow: (e) => pages.entryRow(e, H), renderBody: H.renderBody, render });
    else if (r.view === "thoughts") thoughts.page(main, T);
    else if (r.view === "thought") thoughts.reader(main, r.refs, T);
    else if (r.view === "queues") pages.queuesPage(main, H);
    else if (r.view === "findings") pages.findings(main);
    else if (r.view === "authors") pages.authors(main, H);
    else if (r.view === "topic") pages.topic(main, r.file, H);
    else if (r.view === "entry") pages.entry(main, r.uuid, H);
    else if (r.view === "search") search.view(main, r.scope || "self", r.q || "");
    else if (r.view === "family") family.view(main);
    else if (r.view === "ref") pages.remoteEntry(main, r.canonical, r.uuid, H);
    else pages.overview(main, H);
  }

  // A place in another repository: where the library sent the reader, and what that
  // repository's export says the entry is (the hub serves it only for the family, §11.5).
  function elsewhere(x, r, main) {
    append(main, h("h1", null, M.t("why.lib.elsewhere")), h("p", { class: "muted" }, r.centre.canonical || ""));
    x.family.publicState(r.centre.canonical, r.centre.root || "").then((got) => {
      const e = got.state && got.state.entries.find((y) => y.uuid === r.uuid);
      append(main, h("p", null, e ? e.title : got.error || M.t("why.lib.not_found")));
    });
  }

  function draw(x, route, main, aside) {
    clear(main);
    clear(aside);
    place(x, route, main, aside);
  }

  function toolbar(x, route) {
    return h("nav", { class: "why-places", "aria-label": M.t("why.lib.places") },
      Object.keys(PLACES).map((view) => h("a", { href: x.slug + (view === "overview" ? "" : "/" + view),
        "aria-current": route.view === view ? "page" : null }, PLACES[view]())));
  }

  M.views.why = async function (ctx, root, args) {
    clear(root);
    const status = h("p", { class: "muted", role: "status" }, M.t("why.lib.loading"));
    append(root, status);
    try {
      await load();
    } catch (err) {
      append(clear(root), M.errorBox(err));
      return;
    }
    if (!host || host.base !== ctx.base) {
      const made = await makeHost(ctx);
      if (made.code === "ktw_not_configured") {
        append(clear(root), M.why.emptyState(ctx));
        return;
      }
      if (made.error) {
        append(clear(root), h("h2", null, M.t("why.title")), h("p", { class: "flag" }, made.error));
        return;
      }
      host = Object.assign(made, { base: ctx.base });
    }
    const route = routeOf(args);
    host.setRoute(route);
    const main = h("div", { class: "ktw-root why-main", translate: "no" });
    const aside = h("aside", { class: "ktw-root ktw-aside why-aside", translate: "no" });
    append(clear(root), toolbar(host, route), h("div", { class: "why-layout" }, main, aside));
    draw(host, route, main, aside);
  };

  M.ktwHost = { SCRIPTS, STYLES, routeOf, failure, provider, load };
})(window.Maity);
