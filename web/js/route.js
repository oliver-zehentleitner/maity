// The dashboard's address (docs/api.md §16.11): a path, as a forge has it,
// read from location.pathname and changed with the History API. Every link
// in the views is a path ("/new", "/<owner>/<slug>/board"); this file is the
// one place that knows how the address bar holds it. In fixture mode, a page
// opened from file:// (a development tool, never served), the address
// cannot carry a path: there the same path travels in the fragment
// (index.html#/new). See web/context/routing.md.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const fixture = window.location.protocol === "file:";

  // First segments the hub answers itself (§16.11, "Hub paths"): a link
  // there leaves the dashboard, and a sign-in's next never points there.
  const HUB = ["api", "assets", "join", "r", "mail", "badge", "robots.txt", "impressum", "privacy", "terms"];
  const firstOf = (path) => path.split(/[/?#]/)[1] || "";
  const hubPath = (path) => HUB.includes(firstOf(path)) || /^sitemap(-\d+)?\.xml$/.test(firstOf(path));

  // A path of the dashboard: one "/", no "//" anywhere, no backslash (a
  // browser reads "/\\x" as "//x", another origin), no fragment, no space,
  // no control or format character (Unicode Cc and Cf: C0, DEL, C1, bidi
  // overrides, zero-width), not under a hub path: the hub's own rules for a
  // next (paths.safe_next). This is the boundary for every link the views
  // write and for a sign-in's next (§2.6.5).
  const UNSAFE = /[\s\p{Cc}\p{Cf}]/u;
  const safePath = (value) => typeof value === "string" && value.startsWith("/") && !value.includes("//") && !value.includes("\\")
    && !value.includes("#") && !UNSAFE.test(value);
  function isRoute(value) {
    return safePath(value) && !hubPath(value);
  }
  // A page the hub serves itself on this host (the legal pages, §16.7.1):
  // the same checks, a link the browser follows as a page load.
  const isHubPage = (value) => safePath(value) && hubPath(value) && /^\/(impressum|privacy|terms)(\/[A-Za-z0-9:._-]+)?$/.test(value);

  // Where the page is: its path, its query and, over http(s), its fragment
  // (the device code travels there, never to the hub, §2.6.2).
  function current() {
    if (fixture) {
      const f = window.location.hash.replace(/^#/, "");
      const q = f.indexOf("?");
      const path = q < 0 ? f : f.slice(0, q);
      return { path: path.startsWith("/") ? path : "/", query: new URLSearchParams(q < 0 ? "" : f.slice(q + 1)), fragment: "" };
    }
    return { path: window.location.pathname || "/", query: new URLSearchParams(window.location.search), fragment: window.location.hash.replace(/^#/, "") };
  }

  // The href an <a> gets for a path; dom.h writes every route through it.
  const href = (path) => (fixture ? "#" + path : path);

  let onChange = null;
  // The address as go() and a link name it: path and query.
  const here = () => (fixture ? window.location.hash.replace(/^#/, "") : window.location.pathname + window.location.search);
  // Go to a path: a new entry in the history, or with replace the current
  // one changed (a redirect, a removed query). The view follows at once.
  // The address one is at already changes nothing, as a link to the same
  // fragment did: no second entry, no view drawn again under a form.
  // True when the address changed (and the view follows), false otherwise.
  function go(path, opts) {
    const replace = !!(opts && opts.replace);
    if (path === here()) return false;
    if (fixture) {
      // hashchange draws the view.
      if (replace) window.location.replace("#" + path);
      else window.location.hash = "#" + path;
      return true;
    }
    window.history[replace ? "replaceState" : "pushState"](null, "", path);
    if (onChange) onChange();
    return true;
  }

  // The view is drawn again on every change of the address: back and
  // forward, a link, go().
  function listen(fn) {
    onChange = fn;
    window.addEventListener(fixture ? "hashchange" : "popstate", fn);
    if (fixture) return;
    // A click on a link of the dashboard stays in the page; a modified
    // click, another target or a hub path is the browser's.
    document.addEventListener("click", (e) => {
      if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
      const a = e.target && e.target.closest ? e.target.closest("a[href]") : null;
      if (!a || (a.getAttribute("target") && a.getAttribute("target") !== "_self") || a.hasAttribute("download")) return;
      const to = a.getAttribute("href");
      if (!isRoute(to)) return;
      e.preventDefault();
      go(to);
    });
  }

  // The address without its fragment, nothing drawn again: the device code
  // is read once and then no longer stands in the address bar (§16.11).
  function dropFragment() {
    if (!fixture && window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  M.route = { fixture, isRoute, isHubPage, current, href, go, listen, dropFragment };
})(window.Maity);
