// The product line (docs/api.md §16.13): one small line about Maity at the end of
// every page the dashboard draws, in the language of the page, never set by an
// operator. It stands in <footer id="product-line"> after <main>, so every view, the
// sign-in, the invitation and the full maintenance page end with it, whatever
// replaced <main>; render() draws it again with each view (the language may change).
//
// [Maity icon] Maity 2026 · Made with ♥ by Oliver Zehentleitner on [GitHub icon] & [Maity icon] · Found a bug? · Found a vulnerability?
//
// The icons are inline SVG with presentation attributes only (§16.13, "The icons");
// css/app.css switches the Maity mark's fill under a dark theme.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const SVG = "http://www.w3.org/2000/svg";
  const ISSUES = "https://github.com/oliver-zehentleitner/maity/issues";
  // Where a vulnerability is reported privately, never as a public issue.
  const SECURITY = "https://github.com/oliver-zehentleitner/maity/blob/main/SECURITY.md";
  const GITHUB = "https://github.com/oliver-zehentleitner";
  const PROFILE = "https://maity.team/oliver-zehentleitner";
  const NAME = "Oliver Zehentleitner";
  // The sentence's placeholders, each exactly once; any other one, or one twice, and the
  // English sentence stands instead (§16.13, "Words").
  const PLACES = ["heart", "name", "github", "maity"];
  const PLACEHOLDER = /\{([a-z][a-z0-9_]*)\}/g;

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  // The small mark of brand/maity-mark-small.svg, without its role, label and <title>:
  // it is decorative, or inside a link that has its name.
  function maityMark() {
    const svg = svgEl("svg", { viewBox: "0 0 64 64", width: "16", height: "16", "aria-hidden": "true", focusable: "false", class: "product-mark" });
    svg.appendChild(svgEl("rect", { x: 24, y: 2, width: 16, height: 16, rx: 3, fill: "#1a66d9", class: "product-mark-t" }));
    [[50, 22], [50, 44], [32, 54], [14, 44], [14, 22]].forEach(([cx, cy]) =>
      svg.appendChild(svgEl("circle", { cx, cy, r: 8, fill: "#1d2125", class: "product-mark-seat" })));
    return svg;
  }

  // GitHub's mark (Octicons, MIT), the path the header draws for a GitHub repository.
  function githubMark() {
    const svg = svgEl("svg", { viewBox: "0 0 16 16", width: "16", height: "16", "aria-hidden": "true", focusable: "false", class: "product-mark" });
    svg.appendChild(svgEl("path", { d: M.forgeMarkPath("github"), fill: "currentColor" }));
    return svg;
  }

  const external = (href, attrs, ...children) =>
    M.dom.h("a", Object.assign({ href, target: "_blank", rel: "noopener noreferrer" }, attrs), ...children);

  // A sentence that names each placeholder exactly once and no other.
  function wellFormed(text) {
    if (typeof text !== "string") return false;
    const found = Array.from(text.matchAll(PLACEHOLDER), (m) => m[1]);
    return found.length === PLACES.length && PLACES.every((p) => found.filter((f) => f === p).length === 1);
  }

  // The translated sentence as pieces: its text stays text, only the four placeholders
  // become the fixed elements.
  function sentence(values) {
    const own = M.t("product.made_by");
    const text = wellFormed(own) ? own : M.i18n.english("product.made_by");
    const out = [];
    let last = 0;
    for (const m of text.matchAll(PLACEHOLDER)) {
      if (m.index > last) out.push(text.slice(last, m.index));
      out.push(values[m[1]]);
      last = m.index + m[0].length;
    }
    if (last < text.length) out.push(text.slice(last));
    return out;
  }

  function line() {
    const h = M.dom.h;
    const heart = h("span", { class: "product-heart", role: "img", "aria-label": M.t("product.love") }, "♥");
    const values = {
      heart,
      name: M.dom.h("span", { translate: "no" }, NAME),
      github: external(GITHUB, { class: "product-icon", "aria-label": "GitHub", translate: "no" }, githubMark()),
      maity: external(PROFILE, { class: "product-icon", "aria-label": "Maity", translate: "no" }, maityMark()),
    };
    return [
      h("span", { class: "product-part" }, maityMark(), " ", h("span", { translate: "no" }, "Maity"), " ", String(new Date().getFullYear())),
      h("span", { class: "product-sep", "aria-hidden": "true" }, " · "),
      h("span", { class: "product-part" }, sentence(values)),
      h("span", { class: "product-sep", "aria-hidden": "true" }, " · "),
      h("span", { class: "product-part" }, external(ISSUES, null, M.t("product.bug"))),
      h("span", { class: "product-sep", "aria-hidden": "true" }, " · "),
      h("span", { class: "product-part" }, external(SECURITY, null, M.t("product.security"))),
    ];
  }

  // Whether this view ends with the line: render() says so for each view, a language
  // switch draws it again only where it stands.
  let shown = true;

  function draw() {
    const footer = document.getElementById("product-line");
    if (!footer) return;
    const { append, clear } = M.dom;
    clear(footer);
    if (shown) append(footer, line());
  }

  function show(on) {
    shown = !!on;
    draw();
  }

  M.productLine = { draw, show, wellFormed };
})(window.Maity);
