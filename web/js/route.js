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
  // A route with a place on its page (`/<owner>/<slug>/contract#s-6.8`, §6.8): a route and
  // one anchor of letters, digits, `.`, `_` and `-` after a single `#`. Never a sign-in's
  // next, which stays a plain route; only a link the views write.
  const ANCHOR = /^[A-Za-z][A-Za-z0-9._-]{0,99}$/;
  function splitAnchor(value) {
    if (typeof value !== "string") return null;
    const at = value.indexOf("#");
    if (at < 0) return null;
    const path = value.slice(0, at), anchor = value.slice(at + 1);
    return isRoute(path) && ANCHOR.test(anchor) ? { path, anchor } : null;
  }
  const isAnchored = (value) => splitAnchor(value) !== null;
  // A page the hub serves itself on this host (the legal pages, §16.7.1):
  // the same checks, a link the browser follows as a page load.
  const isHubPage = (value) => safePath(value) && hubPath(value) && /^\/(impressum|privacy|terms)(\/[A-Za-z0-9:._-]+)?$/.test(value);

  // Where the page is: its path, its query and, over http(s), its fragment
  // (the device code travels there, never to the hub, §2.6.2).
  function current() {
    if (fixture) {
      // The route travels in the fragment; a place on its page after a second `#`.
      const all = window.location.hash.replace(/^#/, "");
      const cut = all.indexOf("#");
      const f = cut < 0 ? all : all.slice(0, cut);
      const q = f.indexOf("?");
      const path = q < 0 ? f : f.slice(0, q);
      return { path: path.startsWith("/") ? path : "/", query: new URLSearchParams(q < 0 ? "" : f.slice(q + 1)), fragment: cut < 0 ? "" : all.slice(cut + 1) };
    }
    return { path: window.location.pathname || "/", query: new URLSearchParams(window.location.search), fragment: window.location.hash.replace(/^#/, "") };
  }

  // The href an <a> gets for a path; dom.h writes every route through it.
  const href = (path) => (fixture ? "#" + path : path);

  let onChange = null;
  // The address as go() and a link name it: path and query.
  const here = () => (fixture ? window.location.hash.replace(/^#/, "").replace(/#.*$/, "") : window.location.pathname + window.location.search);
  // Go to a path: a new entry in the history, or with replace the current
  // one changed (a redirect, a removed query). The view follows at once.
  // The address one is at already changes nothing, as a link to the same
  // fragment did: no second entry, no view drawn again under a form.
  // True when the address changed (and the view follows), false otherwise.
  // With quiet the current entry is changed and no view drawn again: a query the page already
  // follows (the page's language, js/i18n.js). Over http(s) the place after `#` stays.
  function go(path, opts) {
    const quiet = !!(opts && opts.quiet);
    const replace = !!(opts && opts.replace);
    if (path === here()) return false;
    if (quiet) {
      window.history.replaceState(window.history.state, "", fixture ? "#" + path : path + window.location.hash);
      return true;
    }
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
      const anchored = splitAnchor(to);
      if (anchored) {
        e.preventDefault();
        // The page one is on: only the place changes, nothing is drawn or read again.
        if (anchored.path === here()) jump(anchored.anchor);
        else { window.history.pushState(null, "", to); if (onChange) onChange(); }
        return;
      }
      if (!isRoute(to)) return;
      e.preventDefault();
      go(to);
    });
  }

  // A place on the page drawn: scrolled to and, over http(s), named in the address so a
  // reload or a copied link opens it there. In fixture mode the route holds the fragment;
  // the place is only scrolled to, as a changed fragment would draw the view again.
  function jump(anchor) {
    if (!ANCHOR.test(anchor)) return false;
    const el = document.getElementById(anchor);
    if (!el) return false;
    if (!fixture) window.history.replaceState(null, "", window.location.pathname + window.location.search + "#" + anchor);
    el.scrollIntoView();
    return true;
  }

  // The address without its fragment, nothing drawn again: the device code
  // is read once and then no longer stands in the address bar (§16.11).
  function dropFragment() {
    if (!fixture && window.location.hash) window.history.replaceState(null, "", window.location.pathname + window.location.search);
  }

  // An anchored route's href: the route as `href` writes it, the place after it.
  const anchoredHref = (value) => { const x = splitAnchor(value); return x ? href(x.path) + "#" + x.anchor : null; };

  M.route = { fixture, isRoute, isAnchored, anchoredHref, isHubPage, current, href, go, listen, dropFragment, jump };
})(window.Maity);
