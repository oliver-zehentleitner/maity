// The public landing page's one script (docs/api.md §16.7, progressive
// enhancement), served by the hub at /assets/landing/landing.js. The page is complete without it: every text is in the
// HTML, the demo and the scales show their end state, the FAQ opens as
// <details>. This file only adds what needs a script, and nothing else:
// - the theme switch: data-theme on <html>, kept in this browser only;
// - the demo's loop: .demo-on on a .demo section while it is on screen
//   (the CSS types and fades its lines);
// - the scales as tabs: .scales-tabs, one column shown at a time;
// - counters ([data-lp-count]) counting up to the number the page holds.
// It reads only this page's DOM, makes no request, and writes text with
// textContent, never content as HTML. Under prefers-reduced-motion it adds
// no motion: no demo loop, no counting.
"use strict";

(function () {
  const root = document.documentElement;
  const KEY = "maity-landing-theme";
  const still = !!(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches);

  // ---- theme -----------------------------------------------------------

  function stored() {
    try { return window.localStorage.getItem(KEY); } catch (err) { return null; }
  }
  function store(value) {
    try { window.localStorage.setItem(KEY, value); } catch (err) { /* kept for this page only */ }
  }
  // The theme shown: the visitor's choice, else the system's.
  function current() {
    const set = root.getAttribute("data-theme");
    if (set === "light" || set === "dark") return set;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  }
  function theme() {
    const saved = stored();
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
    document.querySelectorAll("[data-lp-theme]").forEach((button) => {
      const show = () => button.setAttribute("aria-pressed", String(current() === "dark"));
      show();
      button.hidden = false;
      button.addEventListener("click", () => {
        const next = current() === "dark" ? "light" : "dark";
        root.setAttribute("data-theme", next);
        store(next);
        show();
      });
    });
  }

  // ---- demo ------------------------------------------------------------

  function demo() {
    if (still) return;
    const sections = Array.prototype.slice.call(document.querySelectorAll(".demo"));
    if (!sections.length) return;
    if (!("IntersectionObserver" in window)) {
      sections.forEach((s) => s.classList.add("demo-on"));
      return;
    }
    const seen = new IntersectionObserver((entries) => {
      entries.forEach((e) => e.target.classList.toggle("demo-on", e.isIntersecting));
    }, { threshold: 0.3 });
    sections.forEach((s) => seen.observe(s));
  }

  // ---- scales as tabs --------------------------------------------------

  let tabsMade = 0;
  function scales() {
    document.querySelectorAll(".scales").forEach((section) => {
      const grid = section.querySelector(".scales-grid");
      if (!grid) return;
      const columns = Array.prototype.slice.call(grid.children);
      const titles = columns.map((c) => c.querySelector("h3"));
      if (columns.length < 2 || titles.some((t) => !t)) return;
      tabsMade += 1;
      const list = document.createElement("div");
      list.className = "scales-tablist";
      list.setAttribute("role", "tablist");
      const buttons = columns.map((column, i) => {
        const id = "lp-scale-" + tabsMade + "-" + i;
        column.id = column.id || id + "-panel";
        column.setAttribute("role", "tabpanel");
        column.setAttribute("aria-labelledby", id);
        const b = document.createElement("button");
        b.type = "button";
        b.id = id;
        b.className = "scales-tab";
        b.setAttribute("role", "tab");
        b.setAttribute("aria-controls", column.id);
        b.textContent = titles[i].textContent;
        list.appendChild(b);
        return b;
      });
      function pick(n, focus) {
        buttons.forEach((b, i) => {
          b.setAttribute("aria-selected", String(i === n));
          b.tabIndex = i === n ? 0 : -1;
          columns[i].setAttribute("aria-hidden", String(i !== n));
        });
        if (focus) buttons[n].focus();
      }
      buttons.forEach((b, i) => {
        b.addEventListener("click", () => pick(i, false));
        // Arrow keys move between tabs, as a tab list does.
        b.addEventListener("keydown", (e) => {
          const step = e.key === "ArrowRight" ? 1 : e.key === "ArrowLeft" ? -1 : 0;
          if (!step) return;
          e.preventDefault();
          pick((i + step + buttons.length) % buttons.length, true);
        });
      });
      // The tab bar sits above the two columns (`.scales-body`: the panels and the rings), not
      // inside them; without that wrapper it stays before the grid, as it always did.
      const parent = grid.parentNode;
      const body = parent.classList && parent.classList.contains("scales-body") ? parent : grid;
      body.parentNode.insertBefore(list, body);
      section.classList.add("scales-tabs");
      pick(0, false);
    });
  }

  // ---- counters --------------------------------------------------------

  // The number in the text, its digits only; the text is put back as the
  // page had it at the end, so the hub's own formatting stays.
  function counters() {
    if (still) return;
    document.querySelectorAll("[data-lp-count]").forEach((el) => {
      const end = el.textContent;
      // Only a plain number counts up; a text like "< 5" stays as it is.
      if (!/^[\s\d.,\u00a0\u202f']+$/.test(end)) return;
      const target = parseInt(end.replace(/[^0-9]/g, ""), 10);
      if (!target || !("IntersectionObserver" in window) || !window.requestAnimationFrame) return;
      const format = (n) => new Intl.NumberFormat(root.lang || undefined).format(n);
      const seen = new IntersectionObserver((entries) => {
        if (!entries.some((e) => e.isIntersecting)) return;
        seen.disconnect();
        const start = performance.now();
        const run = (now) => {
          const done = Math.min(1, (now - start) / 1200);
          if (done < 1) {
            el.textContent = format(Math.round(target * (1 - Math.pow(1 - done, 3))));
            window.requestAnimationFrame(run);
          } else {
            el.textContent = end;
          }
        };
        window.requestAnimationFrame(run);
      }, { threshold: 0.5 });
      seen.observe(el);
    });
  }

  function start() {
    theme();
    demo();
    scales();
    counters();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
