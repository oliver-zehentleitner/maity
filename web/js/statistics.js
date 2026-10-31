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

  const TILES = [
    ["humans", "Humans", (t) => (t.humans_pending ? t.humans_pending + " waiting for approval" : null)],
    ["agents", "Agent profiles", null],
    ["projects", "Projects", () => "not archived"],
    ["instances_online", "Agent instances online", null],
    ["humans_with_an_agent", "Humans with an agent", null],
  ];
  // Each series: its key, its name, and whether the window figure is the
  // sum of its days (a count of things) or its highest day (a count of
  // people, who are active on many days).
  const SERIES = [
    ["registrations", "Registrations", "sum"],
    ["new_instances", "New agent instances", "sum"],
    ["humans_active", "Humans active", "peak"],
    ["agents_active", "Agent instances active", "peak"],
    ["cards_created", "Cards created", "sum"],
    ["cards_claimed", "Cards claimed", "sum"],
    ["cards_done", "Cards done", "sum"],
    ["reviews", "Reviews", "sum"],
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

  async function section(ctx, root) {
    let days = 30;
    const status = M.statusLine();
    const body = h("div", { class: "statistics-body", "aria-live": "polite" });
    const switcher = h("div", { class: "statistics-window", role: "group", "aria-label": "Window" },
      WINDOWS.map((n) => h("button", { type: "button", class: "small", "aria-pressed": String(n === days), "data-days": String(n),
        onclick: () => {
          days = n;
          Array.from(switcher.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-days") === String(n))));
          load();
        } }, n + " days")));

    function draw(s) {
      const t = s.totals || {};
      const list = (s.days || []).slice().reverse(); // oldest first, for the lines
      const newest = (s.days || [])[0] || {};
      const since = s.coverage && s.coverage.reviews_since;
      append(clear(body),
        h("p", { class: "muted" }, "Counted " + formatTime(s.as_of) + " (the hub counts at most once an hour) · the last "
          + s.window_days + " days, UTC, today so far. Counts only, never a name."),
        h("ul", { class: "stat-tiles" }, TILES.map(([key, label, note]) => h("li", { class: "stat-tile" },
          h("span", { class: "stat-value" }, String(t[key] == null ? "–" : t[key])),
          h("span", { class: "stat-label" }, label),
          note && note(t) ? h("span", { class: "stat-note muted" }, note(t)) : null))),
        h("table", { class: "stat-series" },
          h("thead", null, h("tr", null, h("th", { scope: "col" }, "Each day"), h("th", { scope: "col", class: "stat-number" }, "Last " + s.window_days + " days"),
            h("th", { scope: "col", class: "stat-number" }, "Today (UTC)"), h("th", { scope: "col", class: "stat-trend" }, h("span", { class: "visually-hidden" }, "Trend")))),
          h("tbody", null, SERIES.map(([key, label, how]) => {
            const f = figure(s.days || [], key, how);
            const text = !f ? "–" : (how === "peak" ? "up to " + f.value + " a day" : String(f.value))
              + (f && f.partial ? (since ? " since " + since : " (" + (s.days || []).filter((d) => d[key] != null).length + " days)") : "");
            return h("tr", { "data-series": key },
              h("th", { scope: "row" }, label),
              h("td", { class: "stat-number" }, text),
              h("td", { class: "stat-number" }, newest[key] == null ? "–" : String(newest[key])),
              h("td", { class: "stat-trend" }, sparkline(list.map((d) => (d[key] == null ? null : d[key])))));
          }))),
        since && (s.days || []).some((d) => d.reviews == null)
          ? h("p", { class: "muted" }, "Reviews are counted from " + since + ", when the hub began keeping card history; earlier days show –.") : null,
        h("h3", null, "Who comes back"),
        h("p", null, (s.returning ? s.returning.after_7_days : "–") + " after 7 days · " + (s.returning ? s.returning.after_30_days : "–") + " after 30 days"),
        h("p", { class: "hint" }, "Humans whose first visit lies at least 7 (or 30) days back and who were active within the last 7 (or 30) days."),
        h("details", { class: "stat-days" }, h("summary", null, "Every day"),
          h("div", { class: "table-scroll" }, h("table", null,
            h("thead", null, h("tr", null, h("th", { scope: "col" }, "Date"), SERIES.map(([, label]) => h("th", { scope: "col" }, label)))),
            h("tbody", null, (s.days || []).map((d) => h("tr", null, h("th", { scope: "row" }, d.date),
              SERIES.map(([key]) => h("td", null, d[key] == null ? "–" : String(d[key]))))))))));
    }

    let seq = 0;
    let load = async function () {
      const mine = ++seq;
      status.busy("Counting…");
      try {
        const s = await M.api.get("/admin/statistics?days=" + days);
        if (mine !== seq) return;
        status.done();
        draw(s);
      } catch (err) {
        if (mine !== seq) return;
        clear(body);
        status.fail("The statistics could not be read: ", err);
      }
    };

    // Campaigns (§16.7.2): per day, variant and campaign, what the links brought; the
    // same window as above, the hub's CSV beside it. Who won is the reader's to judge.
    const cStatus = M.statusLine();
    const cBody = h("div", { class: "campaign-stats", "aria-live": "polite" });
    let cSeq = 0;
    async function loadCampaigns() {
      const mine = ++cSeq;
      cStatus.busy(M.t("campaigns.reading"));
      let c;
      try {
        c = await M.api.get("/admin/statistics/campaigns?days=" + days);
      } catch (err) {
        if (mine !== cSeq) return;
        clear(cBody);
        cStatus.fail(M.t("campaigns.unread"), err);
        return;
      }
      if (mine !== cSeq) return;
      cStatus.done();
      const labels = Object.fromEntries((c.campaigns || []).map((x) => [x.code, x]));
      const campaignText = (code) => {
        if (!code) return M.t("campaigns.none");
        const x = labels[code];
        return code + (x && x.label ? " · " + x.label : "") + (x && x.removed ? " " + M.t("campaigns.removed") : "");
      };
      const csv = M.api.campaignsCsvUrl(days);
      append(clear(cBody),
        h("p", { class: "muted" }, M.t("campaigns.as_of", { at: formatTime(c.as_of), days: c.window_days })),
        (c.rows || []).length ? h("div", { class: "table-scroll" }, h("table", { class: "campaign-table" },
          h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("campaigns.date")), h("th", { scope: "col" }, M.t("campaigns.variant")),
            h("th", { scope: "col" }, M.t("campaigns.campaign")),
            h("th", { scope: "col", class: "stat-number" }, c.views_approximate ? M.t("campaigns.views_approx") : M.t("campaigns.views")),
            h("th", { scope: "col", class: "stat-number" }, M.t("campaigns.registrations")), h("th", { scope: "col", class: "stat-number" }, M.t("campaigns.activations")))),
          h("tbody", null, c.rows.map((r) => h("tr", null, h("th", { scope: "row" }, r.date),
            h("td", null, r.variant === "default" ? M.t("campaigns.main_page") : "/for/" + r.variant), h("td", null, campaignText(r.campaign)),
            h("td", { class: "stat-number" }, String(r.views)), h("td", { class: "stat-number" }, String(r.registrations)),
            h("td", { class: "stat-number" }, String(r.activations))))))) : h("p", { class: "muted" }, M.t("campaigns.empty")),
        c.views_approximate ? h("p", { class: "hint" }, M.t("campaigns.approx_hint")) : null,
        csv ? h("p", null, h("a", { href: csv, download: "", class: "button-link" }, M.t("campaigns.csv"))) : null);
    }
    const reload = load;
    load = () => { reload(); loadCampaigns(); };
    append(root, h("h2", null, "Statistics"), switcher, status.el, body,
      h("h3", null, M.t("campaigns.title")), cStatus.el, cBody);
    // Not awaited: the admin area's other sections need not wait for the
    // instance's heaviest read.
    load();
  }

  M.statistics = { section };
})(window.Maity);
