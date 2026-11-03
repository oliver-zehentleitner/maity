// The frame of the pages without a session (docs/api.md §16.7.5): the landing page's header and
// full footer around /login and /register, from GET /site/chrome in the page's language, with
// the landing page's two stylesheets under /assets/landing/. The hub draws the same frame around
// its landing and legal pages from the same model (hub/src/maity_hub/render.py), so the markup
// here is that file's. The stylesheets are on only while such a page stands: landing.css sets
// :root, body, headings and links for the whole document, so every other view turns them off
// (app.js render). A failed read draws the page without header and footer, as sign-in never
// depends on this call (§16.7.4); the door's own layout still comes from public-pages.css.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;
  // Asked without ?v=<digest>: the hub then answers the current file with no-cache and an ETag
  // (hub/src/maity_hub/landing_files.py), so a revalidation costs no body and never goes stale.
  const SHEETS = ["/assets/landing/landing.css", "/assets/landing/public-pages.css"];
  const ON = "public-frame";
  let links = [];
  let header = null;
  let footer = null;
  // Each drawing counts; an answer for an earlier one, or one after leave(), draws nothing.
  let round = 0;

  function sheets(on) {
    if (on && !links.length) {
      links = SHEETS.map((href) => {
        const link = document.createElement("link");
        link.setAttribute("rel", "stylesheet");
        link.setAttribute("href", href);
        document.head.appendChild(link);
        return link;
      });
    }
    links.forEach((link) => { link.disabled = !on; });
  }
  function mark(on) {
    const root = document.documentElement;
    const names = (root.className || "").split(/\s+/).filter((c) => c && c !== ON);
    root.className = (on ? names.concat(ON) : names).join(" ");
  }
  function drop() {
    if (header) header.remove();
    if (footer) footer.remove();
    header = footer = null;
    const app = document.getElementById("header");
    if (app) app.hidden = false;
  }

  // An address of the model as a link: an https URL, or a path of this host. A dashboard route
  // goes through M.route.href (fixture mode keeps it in the fragment); every other path, the
  // landing page with its section, a legal page or ?lang=, is a page load as on the hub's pages.
  function link(item, attrs) {
    const href = item.href;
    const path = typeof href === "string" ? href.split(/[?#]/)[0] : "";
    const local = typeof href === "string" && /^\/(?![/\\])/.test(href) && !/[\s\p{Cc}\p{Cf}\\]/u.test(href);
    if (!local && !M.dom.safeUrl(href)) return h("span", null, item.label);
    const a = h("a", attrs || null, item.label);
    a.setAttribute("href", local && path !== "/" && M.route.isRoute(href.split("#")[0]) ? M.route.href(href.split("#")[0]) : href);
    // As every outside link of the dashboard: no referrer, since these pages' addresses can hold an
    // invitation's token (?next=/invite/…); a social link that names its owner's profile is rel=me (§16.7.5).
    if (!local) a.setAttribute("rel", (item.rel === "me" ? ["noopener", "noreferrer", "me"] : ["noopener", "noreferrer"]).join(" "));
    return a;
  }

  // The mark as the hub inlines it (landing_assets/mark.svg), without its style attributes: the
  // dashboard's policy (default-src 'self', no inline style) refuses them. Its colours, the
  // header's tokens, come from public-pages.css (`.site-header .mark rect`, …).
  const SVG = "http://www.w3.org/2000/svg";
  function home() {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 64 64"], ["aria-hidden", "true"], ["focusable", "false"], ["class", "mark"]].forEach(([k, v]) => svg.setAttribute(k, v));
    const part = (tag, attrs) => {
      const el = document.createElementNS(SVG, tag);
      Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, v));
      svg.appendChild(el);
    };
    part("rect", { x: "26", y: "4", width: "12", height: "12", rx: "3" });
    [[51, 21], [51, 43], [32, 54], [13, 43], [13, 21]].forEach(([cx, cy]) => part("circle", { cx: String(cx), cy: String(cy), r: "6" }));
    part("path", { d: "M23.5 38V31a4.25 4.25 0 0 1 8.5 0v7M32 31a4.25 4.25 0 0 1 8.5 0v7", fill: "none", "stroke-width": "3.5" });
    const a = h("a", { class: "brand" }, svg, "maity");
    // The instance's start page, the hub's own (§16.7): a page load, in fixture mode too.
    a.setAttribute("href", "/");
    return a;
  }

  // The landing page's header: the mark, the sections, sign in and the call to action. The page
  // being drawn marks its own link as the current one.
  function siteHeader(model, current) {
    const top = model.header || {};
    const mine = (item) => (current && item && typeof item.href === "string" && item.href.split("?")[0] === current ? { "aria-current": "page" } : null);
    return h("header", { class: "site-header dz", id: "site-header" }, h("div", { class: "wrap" },
      home(),
      h("nav", { class: "site-nav" }, (top.nav || []).map((item) => link(item))),
      themeButton(),
      top.sign_in ? link(top.sign_in, Object.assign({ class: "signin" }, mine(top.sign_in))) : null,
      top.cta ? link(top.cta, Object.assign({ class: "btn btn-primary" }, mine(top.cta))) : null));
  }

  // The theme stays the visitor's to choose without a session (js/theme.js): one button that
  // turns light and dark over, as the landing page's own switch does.
  function themeButton() {
    if (!M.theme) return null;
    const dark = () => M.theme.get() === "dark" || (M.theme.get() === "system" && !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches));
    const button = h("button", { type: "button", class: "theme-toggle", "aria-label": M.t("frame.theme"), title: M.t("frame.theme"), "aria-pressed": String(dark()) }, "◐");
    button.addEventListener("click", () => {
      M.theme.set(dark() ? "light" : "dark");
      button.setAttribute("aria-pressed", String(dark()));
    });
    return button;
  }

  // The full footer: its columns, the operator's line and the languages, each linked to this page.
  function siteFooter(model) {
    const foot = model.footer || {};
    const columns = (foot.columns || []).filter((c) => c && (c.links || []).length).map((c) => h("nav", { class: "foot-col", "aria-label": c.title },
      h("h3", null, c.title), h("ul", null, c.links.map((item) => h("li", null, link(item))))));
    const languages = (foot.languages || []).map((one) => {
      const a = h("a", { lang: one.tag }, one.name);
      a.setAttribute("href", "?lang=" + encodeURIComponent(one.tag));
      return a;
    });
    return h("footer", { class: "site-footer", id: "site-footer" }, h("div", { class: "wrap" },
      h("div", { class: "foot-cols" }, columns),
      foot.operator ? h("p", { class: "operator" }, foot.operator) : null,
      languages.length ? h("p", { class: "langs" }, languages.flatMap((a, i) => (i ? [" ", a] : [a]))) : null));
  }

  // Called by the page that stands in the frame, once its own content is drawn. `current` is its
  // path (/login, /register), so the header's link to it is marked. Resolves true once the frame
  // stands, false where the read failed or another drawing came first; `drawn` runs then, with
  // the model, before anything else of the page changes.
  async function enter(current, drawn) {
    const mine = ++round;
    sheets(true);
    mark(true);
    // Until the read settles no bar is shown that the frame's header then pushes aside; a frame
    // already standing stays until the new one replaces it.
    const bar = document.getElementById("header");
    if (bar && !header) bar.hidden = true;
    let model;
    try {
      model = await M.api.get("/site/chrome?lang=" + encodeURIComponent(M.i18n.language));
    } catch (err) {
      if (mine === round) drop();
      return false;
    }
    if (mine !== round || !model || !model.header || !model.footer) return false;
    drop();
    const app = bar;
    const main = document.getElementById("main");
    header = siteHeader(model, current);
    footer = siteFooter(model);
    // The words of the model are in its language, the page's may be another (§16.7.5).
    if (model.language && model.language !== M.i18n.language) {
      header.setAttribute("lang", model.language);
      footer.setAttribute("lang", model.language);
    }
    app.parentNode.insertBefore(header, app.nextSibling);
    main.parentNode.insertBefore(footer, main.nextSibling);
    app.hidden = true;
    if (drawn) drawn(model);
    return true;
  }

  // Every other view: the frame and its stylesheets go, the app's header comes back.
  function leave() {
    round++;
    drop();
    sheets(false);
    mark(false);
  }

  M.siteChrome = { enter, leave, active: () => (document.documentElement.className || "").split(/\s+/).includes(ON) };
})(window.Maity);
