// The swarm statistics (docs/api.md §6.22): the team at work, a section of
// the project's Overview (§6.11) — who is online now and what each holds,
// the window's counts per member and in all, the cards done per day — with
// a 7/30/90-day switch. Everything is derived by the hub; the section only
// draws it. There is no Swarm tab and no public swarm page: a public
// project's page carries its reduced numbers (§16.9).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  const WINDOWS = [7, 30, 90];
  // Each column's field and its heading, read from the catalog when drawn.
  const COUNTS = [
    ["cards_done", () => M.t("swarm.col.cards_done")], ["reviews_given", () => M.t("swarm.col.reviews_given")],
    ["prs_merged", () => M.t("swarm.col.prs_merged")], ["handovers", () => M.t("swarm.col.handovers")],
  ];
  const MEDIANS = [["claim_to_done_median_seconds", () => M.t("swarm.col.claim_to_done")], ["review_to_done_median_seconds", () => M.t("swarm.col.review_to_done")]];

  // A median as people read it; null (fewer than three samples) as –.
  function duration(s) {
    if (s === null || s === undefined) return "–";
    const min = Math.round(s / 60);
    // Each unit counts with its own plural forms; two units stand in the
    // order the catalog gives them.
    const mins = (count) => M.t("swarm.duration.min", { count });
    const hrs = (count) => M.t("swarm.duration.h", { count });
    if (min < 60) return mins(min);
    const hours = Math.floor(min / 60);
    if (hours < 48) return min % 60 ? M.t("swarm.duration.h_min", { h: hrs(hours), min: mins(min % 60) }) : hrs(hours);
    const days = M.t("swarm.duration.d", { count: Math.floor(hours / 24) });
    return hours % 24 ? M.t("swarm.duration.d_h", { d: days, h: hrs(hours % 24) }) : days;
  }

  // The cards done per day as a small line, oldest left. Decorative: the
  // total stands beside it and the members' table says the rest.
  function sparkline(days) {
    const W = 160, H = 28, P = 2;
    // Oldest left, whichever order the hub sends (§6.22 sends oldest first).
    const values = days.slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0)).map((d) => d.count || 0);
    const box = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 " + W + " " + H], ["width", W], ["height", H], ["aria-hidden", "true"], ["focusable", "false"], ["class", "sparkline"]]
      .forEach(([k, v]) => box.setAttribute(k, String(v)));
    if (!values.length) return box;
    const max = Math.max(1, ...values);
    const points = values.map((v, i) => (values.length < 2 ? W / 2 : P + (i * (W - 2 * P)) / (values.length - 1)).toFixed(1)
      + "," + (H - P - (v / max) * (H - 2 * P)).toFixed(1)).join(" ");
    const line = document.createElementNS(SVG, "polyline");
    [["points", points], ["fill", "none"], ["class", "spark-line"]].forEach(([k, v]) => line.setAttribute(k, v));
    box.appendChild(line);
    return box;
  }

  function switcher(days, onPick) {
    const box = h("div", { class: "swarm-window", role: "group", "aria-label": M.t("swarm.window") });
    append(box, WINDOWS.map((n) => h("button", { type: "button", class: "small", "aria-pressed": String(n === days), "data-days": String(n),
      onclick: () => {
        Array.from(box.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-days") === String(n))));
        onPick(n);
      } }, M.t("swarm.window.days", { count: n }))));
    return box;
  }

  // The window's table: one row per member, the totals last.
  function table(rows, totals, label) {
    const cells = (r) => [...COUNTS.map(([k]) => h("td", null, String(r[k] == null ? "–" : r[k]))),
      ...MEDIANS.map(([k]) => h("td", null, duration(r[k])))];
    // A box that scrolls sideways is reachable by keyboard, and named.
    return h("div", { class: "table-scroll", tabindex: "0", role: "region", "aria-label": M.t("swarm.table") }, h("table", { class: "swarm-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, M.t("swarm.col.member")),
        COUNTS.concat(MEDIANS).map(([, l]) => h("th", { scope: "col" }, l())))),
      h("tbody", null, rows.map((r) => h("tr", { "data-member": r.member_id || r.handle }, h("th", { scope: "row" }, label(r)), cells(r)))),
      h("tfoot", null, h("tr", { class: "swarm-total" }, h("th", { scope: "row" }, M.t("swarm.all")), cells(totals)))));
  }

  // One read at a time per section, the newest winning: a slower answer to an
  // earlier window never replaces a later one.
  function loader(status, read, draw, failed) {
    let seq = 0;
    return async () => {
      const mine = ++seq;
      status.busy(M.t("swarm.reading"));
      try {
        const s = await read();
        if (mine !== seq) return;
        status.done();
        draw(s);
      } catch (err) {
        if (mine !== seq) return;
        failed(err);
      }
    };
  }

  function notes(s) {
    return [
      h("p", { class: "hint" }, M.t("swarm.note.median")),
      s.coverage && s.coverage.reviews_since ? h("p", { class: "hint" }, M.t("swarm.note.reviews_since", { since: s.coverage.reviews_since })) : null,
    ];
  }

  // ---- the Overview's section ---------------------------------------------

  // Built once per Overview and kept across its redraws, so a redraw of the
  // counts neither reads the swarm again nor loses the chosen window.
  function section(ctx) {
    let days = 30;
    const status = M.statusLine();
    const body = h("div", { class: "swarm-body" });
    const memberLink = (id, fallback) => (ctx.memberById && ctx.memberById[id] ? M.dom.memberRef(ctx, id) : h("span", null, fallback));

    function draw(s) {
      const t = s.totals || {};
      append(clear(body),
        h("p", { class: "muted" }, M.t("swarm.now", { now: formatTime(s.live_at) }), " · ", M.t("swarm.as_of", { count: s.window_days, as_of: formatTime(s.as_of) })),
        h("h4", null, M.t("swarm.live")),
        h("ul", { class: "swarm-live" }, (s.live || []).map((m) => h("li", { class: "swarm-member" + (m.online ? " online" : ""), "data-member": m.member_id },
          h("span", { class: "dot " + (m.online ? "online" : "offline"), "aria-hidden": "true" }),
          h("span", { class: "swarm-name" }, memberLink(m.member_id, m.display_name)),
          h("span", { class: "muted" }, " ", m.online
            ? (m.kind === "agent" && m.instances_online > 1 ? M.t("swarm.online_instances", { count: m.instances_online }) : M.t("swarm.online"))
            : m.last_seen_at ? M.t("swarm.last_seen", { ago: formatAgo(m.last_seen_at, M.api.now()) }) : M.t("swarm.not_seen")),
          (m.holding || []).length
            ? h("ul", { class: "swarm-holding" }, m.holding.map((c) => h("li", null,
              h("a", { href: ctx.link("tasks", c.task_id) }, c.task_id), " " + c.title, h("span", { class: "muted" }, " · ", M.t("swarm.since", { ago: formatAgo(c.since, M.api.now()) })))))
            : null))),
        h("h4", null, M.t("swarm.window.title", { count: s.window_days })),
        h("div", { class: "swarm-per-day" }, h("span", null, t.cards_done == null ? M.t("swarm.cards_done.unknown") : M.t("swarm.cards_done", { count: t.cards_done })), sparkline(t.cards_done_per_day || [])),
        table(s.members || [], t, (r) => memberLink(r.member_id, "@" + (r.name || r.handle))),
        notes(s));
    }

    const load = loader(status, () => M.api.get(ctx.base + "/swarm?days=" + days), draw,
      (err) => { clear(body); status.fail(M.t("swarm.read_failed"), err); });
    const box = h("section", { class: "overview-part overview-swarm", "aria-labelledby": "overview-swarm" },
      h("div", { class: "overview-head" }, h("h3", { id: "overview-swarm" }, M.t("swarm.title")),
        h("span", { class: "muted" }, "· ", M.t("swarm.subtitle"))),
      switcher(days, (n) => { days = n; load(); }), status.el, body);
    load();
    return box;
  }

  M.swarm = { section };
})(window.Maity);
