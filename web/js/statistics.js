// The admin area's Statistics (docs/api.md §16.6): counts the operator
// reads to see whether the instance is used, nothing about a person. The
// totals as tiles; each day series as a row with its window figure, the
// newest day and a small line of the window; the days in full as a folded
// table (the readable view of the lines); who comes back after 7 and 30
// days. A switch for 7, 30 or 90 days. Drawn with the dashboard's own
// SVG, no chart library.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  const WINDOWS = [7, 30, 90];

  // Labels and notes read from the catalog when drawn.
  const TILES = [
    ["humans", () => M.t("stats.tile.humans"), (t) => (t.humans_pending ? M.t("stats.tile.humans.pending", { count: t.humans_pending }) : null)],
    ["agents", () => M.t("stats.tile.agents"), null],
    ["projects", () => M.t("stats.tile.projects"), () => M.t("stats.tile.projects.note")],
    ["instances_online", () => M.t("stats.tile.instances_online"), null],
    ["humans_with_an_agent", () => M.t("stats.tile.humans_with_an_agent"), null],
  ];
  // Each series: its key, its name, and whether the window figure is the
  // sum of its days (a count of things) or its highest day (a count of
  // people, who are active on many days).
  const SERIES = [
    ["registrations", () => M.t("stats.series.registrations"), "sum"],
    ["new_instances", () => M.t("stats.series.new_instances"), "sum"],
    ["humans_active", () => M.t("stats.series.humans_active"), "peak"],
    ["agents_active", () => M.t("stats.series.agents_active"), "peak"],
    ["cards_created", () => M.t("stats.series.cards_created"), "sum"],
    ["cards_claimed", () => M.t("stats.series.cards_claimed"), "sum"],
    ["cards_done", () => M.t("stats.series.cards_done"), "sum"],
    ["reviews", () => M.t("stats.series.reviews"), "sum"],
  ];

  function svg(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  // A line of the window, oldest day left; a day the hub cannot know
  // (null) breaks it. Decorative: the row says the numbers, the table
  // below says every day.
  const W = 120, H = 24, PAD = 2;
  function sparkline(values) {
    const box = svg("svg", { viewBox: "0 0 " + W + " " + H, width: W, height: H, "aria-hidden": "true", focusable: "false" });
    box.setAttribute("class", "sparkline");
    const known = values.filter((v) => v !== null);
    const max = Math.max(1, ...known);
    const x = (i) => (values.length < 2 ? W / 2 : PAD + (i * (W - 2 * PAD)) / (values.length - 1));
    const y = (v) => H - PAD - (v / max) * (H - 2 * PAD);
    let run = [];
    const flush = () => {
      if (run.length > 1) box.appendChild(svg("polyline", { points: run.join(" "), fill: "none", class: "spark-line" }));
      else if (run.length === 1) box.appendChild(svg("circle", { cx: run[0].split(",")[0], cy: run[0].split(",")[1], r: 1.5, class: "spark-dot" }));
      run = [];
    };
    values.forEach((v, i) => { if (v === null) flush(); else run.push(x(i).toFixed(1) + "," + y(v).toFixed(1)); });
    flush();
    return box;
  }

  // The window's figure: a sum of the days, or the highest day; partial
  // when some days are unknown (reviews before the hub kept history).
  function figure(days, key, how) {
    const known = days.map((d) => d[key]).filter((v) => v !== null && v !== undefined);
    if (!known.length) return null;
    return { value: how === "peak" ? Math.max(...known) : known.reduce((a, b) => a + b, 0), partial: known.length < days.length };
  }

  // The window's figure in words: a sum or "up to … a day", and, when some
  // days are unknown, since when or over how many days it counts.
  function figureText(f, how, since, knownDays) {
    if (!f) return "–";
    // A number in a placeholder is formatted for the locale by M.t.
    const value = f.value;
    if (how === "peak") {
      if (!f.partial) return M.t("stats.figure.peak", { value });
      return since ? M.t("stats.figure.peak.since", { value, since }) : M.t("stats.figure.peak.days", { value, count: knownDays });
    }
    if (!f.partial) return M.fmt.number(value);
    return since ? M.t("stats.figure.sum.since", { value, since }) : M.t("stats.figure.sum.days", { value, count: knownDays });
  }

  async function section(ctx, root) {
    let days = 30;
    const status = M.statusLine();
    const body = h("div", { class: "statistics-body", "aria-live": "polite" });
    const switcher = h("div", { class: "statistics-window", role: "group", "aria-label": M.t("stats.window") },
      WINDOWS.map((n) => h("button", { type: "button", class: "small", "aria-pressed": String(n === days), "data-days": String(n),
        onclick: () => {
          days = n;
          Array.from(switcher.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-days") === String(n))));
          load();
        } }, M.t("stats.window.days", { count: n }))));

    function draw(s) {
      const t = s.totals || {};
      const list = (s.days || []).slice().reverse(); // oldest first, for the lines
      const newest = (s.days || [])[0] || {};
      const since = s.coverage && s.coverage.reviews_since;
      append(clear(body),
        h("p", { class: "muted" }, M.t("stats.counted", { when: formatTime(s.as_of) }), " · ", M.t("stats.window.note", { count: s.window_days })),
        h("ul", { class: "stat-tiles" }, TILES.map(([key, label, note]) => h("li", { class: "stat-tile" },
          h("span", { class: "stat-value" }, t[key] == null ? "–" : M.fmt.number(t[key])),
          h("span", { class: "stat-label" }, label()),
          note && note(t) ? h("span", { class: "stat-note muted" }, note(t)) : null))),
        h("table", { class: "stat-series" },
          h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("stats.col.series")), h("th", { scope: "col", class: "stat-number" }, M.t("stats.col.window", { count: s.window_days })),
            h("th", { scope: "col", class: "stat-number" }, M.t("stats.col.today")), h("th", { scope: "col", class: "stat-trend" }, h("span", { class: "visually-hidden" }, M.t("stats.col.trend"))))),
          h("tbody", null, SERIES.map(([key, label, how]) => {
            const f = figure(s.days || [], key, how);
            const text = figureText(f, how, since, (s.days || []).filter((d) => d[key] != null).length);
            return h("tr", { "data-series": key },
              h("th", { scope: "row" }, label()),
              h("td", { class: "stat-number" }, text),
              h("td", { class: "stat-number" }, newest[key] == null ? "–" : M.fmt.number(newest[key])),
              h("td", { class: "stat-trend" }, sparkline(list.map((d) => (d[key] == null ? null : d[key])))));
          }))),
        since && (s.days || []).some((d) => d.reviews == null)
          ? h("p", { class: "muted" }, M.t("stats.reviews_since", { since })) : null,
        h("h3", null, M.t("stats.returning")),
        h("p", null, M.t("stats.returning.7", { value: s.returning ? s.returning.after_7_days : "–" }), " · ",
          M.t("stats.returning.30", { value: s.returning ? s.returning.after_30_days : "–" })),
        h("p", { class: "hint" }, M.t("stats.returning.hint")),
        h("details", { class: "stat-days" }, h("summary", null, M.t("stats.days")),
          h("div", { class: "table-scroll" }, h("table", null,
            h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("stats.col.date")), SERIES.map(([, label]) => h("th", { scope: "col" }, label())))),
            h("tbody", null, (s.days || []).map((d) => h("tr", null, h("th", { scope: "row" }, d.date),
              SERIES.map(([key]) => h("td", null, d[key] == null ? "–" : M.fmt.number(d[key]))))))))));
    }

    let seq = 0;
    async function load() {
      const mine = ++seq;
      status.busy(M.t("stats.counting"));
      try {
        const s = await M.api.get("/admin/statistics?days=" + days);
        if (mine !== seq) return;
        status.done();
        draw(s);
      } catch (err) {
        if (mine !== seq) return;
        clear(body);
        status.fail(M.t("stats.read_failed"), err);
      }
    }

    append(root, h("h2", null, M.t("stats.title")), switcher, status.el, body);
    // Not awaited: the admin area's other sections need not wait for the
    // instance's heaviest read.
    load();
  }

  M.statistics = { section };
})(window.Maity);
