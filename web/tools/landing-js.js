// The landing page's script (hub/src/maity_hub/landing_assets/landing.js,
// docs/api.md §16.7) against a small DOM of its own hooks: the theme
// switch, the demo's .demo-on, the scales as tabs, the counters, and none
// of the motion under prefers-reduced-motion. Node only, no packages.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const SRC = fs.readFileSync(path.join(__dirname, "..", "..", "hub", "src", "maity_hub", "landing_assets", "landing.js"), "utf8");
let failed = 0;
const expect = (ok, what) => { console.log((ok ? "ok   " : "FAIL ") + what); if (!ok) failed += 1; };

class El {
  constructor(tag, cls, attrs) {
    this.tagName = tag.toUpperCase();
    this.className = cls || "";
    this.attrs = Object.assign({}, attrs || {});
    this.children = [];
    this.parentNode = null;
    this.listeners = {};
    this.textContent = "";
    this.hidden = "hidden" in this.attrs;
    const self = this;
    this.classList = {
      add: (c) => { if (!self.classList.contains(c)) self.className = (self.className + " " + c).trim(); },
      contains: (c) => self.className.split(/\s+/).includes(c),
      toggle: (c, on) => { if (on) self.classList.add(c); else self.className = self.className.split(/\s+/).filter((x) => x !== c).join(" "); },
    };
  }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  fire(t, extra) { (this.listeners[t] || []).forEach((f) => f(Object.assign({ preventDefault() {} }, extra || {}))); }
  click() { this.fire("click"); }
  focus() { doc.focused = this; }
  appendChild(c) { c.parentNode = this; this.children.push(c); return c; }
  insertBefore(c, ref) { c.parentNode = this; this.children.splice(this.children.indexOf(ref), 0, c); return c; }
  all() { return this.children.flatMap((c) => [c].concat(c.all())); }
  matches(sel) {
    if (sel.startsWith(".")) return this.classList.contains(sel.slice(1));
    if (sel.startsWith("[")) return sel.slice(1, -1) in this.attrs;
    return this.tagName === sel.toUpperCase();
  }
  querySelectorAll(sel) { return this.all().filter((e) => e.matches(sel)); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
}
const el = (tag, cls, attrs, kids, text) => { const e = new El(tag, cls, attrs); (kids || []).forEach((k) => e.appendChild(k)); if (text !== undefined) e.textContent = text; return e; };

let doc;
function page(reduced, saved) {
  const html = el("html", "", {});
  const theme = el("button", "", { "data-lp-theme": "", hidden: "" });
  const demo = el("section", "demo", { "data-lp-demo": "" });
  const grid = el("div", "scales-grid", {}, ["Solo", "Team", "Company"].map((t) => el("div", "", {}, [el("h3", "", {}, [], t)])));
  // The rings as the hub draws them: without a script ring 1 is active.
  const rings = el("svg", "scales-rings", {}, ["1", "2", "3"].map((n) => el("circle", n === "1" ? "is-active" : "", { "data-ring": n })));
  const scales = el("section", "scales", {}, [el("div", "scales-layout", {}, [grid, el("div", "scales-art", {}, [rings])])]);
  const count = el("span", "", { "data-lp-count": "" }, [], "1,234");
  const few = el("span", "", { "data-lp-count": "" }, [], "< 5");
  const body = el("body", "", {}, [theme, demo, scales, count, few]);
  html.appendChild(body);
  doc = { documentElement: html, readyState: "complete", focused: null, querySelectorAll: (s) => html.querySelectorAll(s), addEventListener() {}, createElement: (t) => new El(t) };
  const observers = [];
  const store = saved ? { "maity-landing-theme": saved } : {};
  const frames = [];
  const win = {
    document: doc,
    localStorage: { getItem: (k) => (k in store ? store[k] : null), setItem: (k, v) => { store[k] = v; } },
    matchMedia: (q) => ({ matches: q.includes("reduced-motion") ? reduced : false }),
    IntersectionObserver: class { constructor(fn) { this.fn = fn; this.seen = []; observers.push(this); } observe(t) { this.seen.push(t); } disconnect() { this.done = true; } },
    requestAnimationFrame: (f) => frames.push(f),
  };
  // As in a browser, the window's members are globals too.
  const ctx = vm.createContext(Object.assign({}, win, { window: win, Intl, performance: { now: () => 0 }, Math, Array, String, parseInt }));
  vm.runInContext(SRC, ctx, { filename: "landing.js" });
  return { html, theme, demo, grid, rings, scales, count, few, observers, store, frames };
}

// The theme: the button shown, data-theme switched and kept.
let p = page(false, null);
expect(!p.theme.hidden && p.theme.getAttribute("aria-pressed") === "false" && p.html.getAttribute("data-theme") === null,
  "theme: the button is shown, the system's theme kept until a choice");
p.theme.click();
expect(p.html.getAttribute("data-theme") === "dark" && p.store["maity-landing-theme"] === "dark" && p.theme.getAttribute("aria-pressed") === "true",
  "theme: a click switches to dark, kept in this browser");
p = page(false, "dark");
expect(p.html.getAttribute("data-theme") === "dark", "theme: the kept choice is set on load");

// The demo: .demo-on while on screen.
p = page(false, null);
const demoSeen = p.observers.find((o) => o.seen.includes(p.demo));
demoSeen.fn([{ target: p.demo, isIntersecting: true }]);
const on = p.demo.classList.contains("demo-on");
demoSeen.fn([{ target: p.demo, isIntersecting: false }]);
expect(on && !p.demo.classList.contains("demo-on"), "demo: .demo-on while on screen, off when it leaves");

// The scales as tabs, named from each column's h3 as text.
const tabs = p.scales.querySelectorAll("button");
expect(p.scales.classList.contains("scales-tabs") && tabs.map((b) => b.textContent).join() === "Solo,Team,Company"
  && tabs[0].getAttribute("aria-selected") === "true" && p.grid.children.map((c) => c.getAttribute("aria-hidden")).join() === "false,true,true",
  "scales: three tabs from the columns' titles, the first shown");
const activeRing = () => p.rings.children.filter((c) => c.classList.contains("is-active")).map((c) => c.getAttribute("data-ring")).join();
expect(activeRing() === "1", "scales: the first tab keeps ring 1 active");
tabs[2].click();
expect(p.grid.children.map((c) => c.getAttribute("aria-hidden")).join() === "true,true,false" && tabs[2].tabIndex === 0,
  "scales: a click shows its column");
expect(activeRing() === "3", "scales: the chosen tab's ring is the active one, alone");
tabs[2].fire("keydown", { key: "ArrowRight" });
expect(tabs[0].getAttribute("aria-selected") === "true" && doc.focused === tabs[0], "scales: the arrow keys move between tabs, round");

// Counters: a plain number counts up and ends as the page wrote it; "< 5" is left alone.
const countSeen = p.observers.find((o) => o.seen.includes(p.count));
expect(!p.observers.some((o) => o.seen.includes(p.few)), "counters: a text that is no plain number is left alone");
countSeen.fn([{ target: p.count, isIntersecting: true }]);
p.frames.shift()(600);
const middle = p.count.textContent;
p.frames.shift()(2000);
expect(middle !== "1,234" && p.count.textContent === "1,234", "counters: counting up, the page's own text at the end (" + middle + ")");

// Reduced motion: no demo loop, no counting; the theme and the tabs still work.
p = page(true, null);
expect(!p.observers.length && !p.theme.hidden && p.scales.classList.contains("scales-tabs") && p.count.textContent === "1,234",
  "reduced motion: no observer, no counting; the theme switch and the tabs stay");

if (failed) { console.log(failed + " failed"); process.exit(1); }
console.log("all ok");
