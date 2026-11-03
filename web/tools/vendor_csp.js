// The vendored Keep the Why views mounted on a page under the hub's policy (tools/vendor_csp.py).
// Loaded as a file of the same origin after the library's scripts; writes its verdict to
// window.KTW_VENDOR_RESULT. Kept out of js/: it is a test page's script, not the dashboard's.
"use strict";

(() => {
  const violations = [];
  document.addEventListener("securitypolicyviolation", (e) => {
    violations.push(e.violatedDirective + " " + (e.blockedURI || "inline") + " " + (e.sourceFile || "") + ":" + (e.lineNumber || 0));
  });
  const errors = [];
  window.addEventListener("error", (e) => errors.push(String(e.message)));
  window.addEventListener("unhandledrejection", (e) => errors.push("rejected: " + String(e.reason && e.reason.message || e.reason)));

  const K = globalThis.KeepTheWhy;
  const VIEWS = ["family", "graph", "pages", "search", "thoughts", "timeline"];

  function box(name) {
    const main = document.createElement("main");
    main.className = "ktw-root";
    main.dataset.place = name;
    document.body.appendChild(main);
    return main;
  }

  async function run() {
    if (!K) throw new Error("globalThis.KeepTheWhy is not defined");
    const missing = VIEWS.filter((v) => !K.views || typeof K.views[v]?.create !== "function");
    if (missing.length) throw new Error("views missing: " + missing.join(", "));
    const raw = await (await fetch("ktw-fixture-state.json")).json();
    const state = K.core.normalizeState(raw);
    let current = { view: "overview" };
    const nav = {
      href: (route) => "/why/" + K.core.routes.format(route).replace(/^#/, ""),
      go(route) { current = route; },
      current: () => current,
    };
    const kept = new Map();
    const prefs = { get: (k, fallback) => (kept.has(k) ? kept.get(k) : fallback), set: (k, v) => kept.set(k, String(v)) };
    const provider = () => ({ state: async () => ({ state, url: "ktw-fixture-state.json" }) });
    const scene = K.scene.create({ state, self: state, scope: "project" });
    const family = K.views.family.create({ scene, nav, provider, host: { mode: () => "export", root: () => "" } });
    const search = K.views.search.create({ scene, nav, family });
    const thoughts = K.views.thoughts.create({ scene, nav, prefs });
    const pages = K.views.pages.create({ scene, nav, prefs, family, search });
    const graphView = K.views.graph.create({ scene, nav, prefs });
    const timeline = K.views.timeline.create({ scene, nav, prefs });
    let G = null;
    const graphOf = () => (G ||= Object.assign({ scale: 1, ox: 0, oy: 0, showEntries: true, showLabels: true, alpha: 1 },
      graphView.assemble(state.topics, state.entries)));
    const aside = document.createElement("aside");
    aside.className = "ktw-root ktw-aside";
    document.body.appendChild(aside);
    const topicHref = (file) => nav.href({ view: "topic", file });
    const H = {
      live: () => false, published: () => true, project: () => null, provider,
      inline: (md) => K.markdown.renderInline(document, md, { topicHref }),
      renderBody: (md) => K.markdown.render(document, md, { topicHref }),
      shareUrl: (route) => ({ url: new URL(nav.href(route), location.origin).href, where: "vendor check" }),
      details: () => aside, miniGraph: () => {},
      entryThoughts: () => [], thoughts, memberLink: (m, href) => href,
      authorLink: (n) => document.createTextNode(n || "-"),
      authorProjects: () => [{ name: "fixture", canonical: "", state, open: nav.href({ view: "authors" }), role: "self", anonymized: false }],
      friendsWaiting: () => [], friendsLoading: () => false, loadFriends: () => {},
      render: () => {}, rerender: () => {},
    };
    const T = {
      graph: async () => graphOf(), light: (g, t) => graphView.lightThought(g, t),
      follow: { busy: () => false, chain: () => {}, all: () => {} },
      findEntry: (uuid) => { const e = state.entries.find((x) => x.uuid === uuid); return e ? { e, own: true, href: nav.href({ view: "entry", uuid }), origin: { state } } : null; },
      bodies: (st) => family.bodies(st), needFriends: () => {}, pick: () => false,
      inline: H.inline, renderBody: H.renderBody, listBox: () => aside, render: () => {},
    };
    pages.overview(box("overview"), H);
    const g = box("graph");
    const wrap = document.createElement("div");
    wrap.className = "ktw-graph-wrap";
    const canvas = document.createElement("canvas");
    canvas.width = 600;
    canvas.height = 400;
    wrap.appendChild(canvas);
    g.appendChild(wrap);
    graphView.run(canvas, graphOf(), { fit: true, onEntry: () => {}, onTopic: () => {} });
    timeline.view(box("timeline"), null, { graph: () => graphOf(), bodies: (st) => family.bodies(st), entryRow: (e) => pages.entryRow(e, H), renderBody: H.renderBody, render: () => {} });
    thoughts.page(box("thoughts"), T);
    family.view(box("family"));
    search.view(box("search"), "self", "api");
    const first = state.entries[0];
    pages.entry(box("entry"), first.uuid || first.id, H);
    // the views settle and the graph draws over animation frames: up to 3 s for ink on its canvas
    const inkOf = () => {
      const px = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
      let n = 0;
      for (let i = 3; i < px.length; i += 4) if (px[i]) n++;
      return n;
    };
    let ink = 0;
    for (let t = 0; t < 30 && !(ink = inkOf()); t++) await new Promise((r) => setTimeout(r, 100));
    await new Promise((r) => setTimeout(r, 300));
    const sheet = [...document.styleSheets].find((s) => (s.href || "").endsWith("/ktw-views.css"));
    const places = {};
    for (const m of document.querySelectorAll("main[data-place]")) places[m.dataset.place] = m.textContent.trim().length;
    return { places, ink, rules: sheet ? sheet.cssRules.length : 0 };
  }

  window.KTW_VENDOR_RESULT = run().then(
    (r) => ({ ...r, violations, errors }),
    (e) => ({ places: {}, rules: 0, violations, errors: errors.concat(String(e && e.stack || e)) }),
  );
})();
