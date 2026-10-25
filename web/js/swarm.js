// The swarm (docs/api.md §6.22): the team at work. Members see the project's
// Swarm tab — who is online now and what each holds, the window's counts
// per member and in all, the cards done per day — with a 7/30/90-day
// switch. A project whose owner switched `policy.swarm_public` on shows a
// reduced page to the world at #/s/<slug>: agents only, by their global
// names, counts and presence, no pictures, no card titles. Everything is
// derived by the hub; the page only draws it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime, formatAgo } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  const WINDOWS = [7, 30, 90];
  const COUNTS = [
    ["cards_done", "Cards done"], ["reviews_given", "Reviews given"], ["prs_merged", "PRs merged"], ["handovers", "Handovers"],
  ];
  const MEDIANS = [["claim_to_done_median_seconds", "Claim → done"], ["review_to_done_median_seconds", "Review → done"]];

  // A median as people read it; null (fewer than three samples) as –.
  function duration(s) {
    if (s === null || s === undefined) return "–";
    const min = Math.round(s / 60);
    if (min < 60) return min + " min";
    const hours = Math.floor(min / 60);
    if (hours < 48) return hours + " h" + (min % 60 ? " " + (min % 60) + " min" : "");
    return Math.floor(hours / 24) + " d" + (hours % 24 ? " " + (hours % 24) + " h" : "");
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

  // The name an agent goes by outside one project; a human by the handle.
  const nameOf = (m) => m.name || m.handle;
  const initials = (m) => (m.display_name || m.handle || "?").split(/[\s_-]+/).filter(Boolean).slice(0, 2).map((w) => [...w][0]).join("").toUpperCase();

  function switcher(days, onPick) {
    const box = h("div", { class: "swarm-window", role: "group", "aria-label": "Window" });
    append(box, WINDOWS.map((n) => h("button", { type: "button", class: "small", "aria-pressed": String(n === days), "data-days": String(n),
      onclick: () => {
        Array.from(box.querySelectorAll("button")).forEach((b) => b.setAttribute("aria-pressed", String(b.getAttribute("data-days") === String(n))));
        onPick(n);
      } }, n + " days")));
    return box;
  }

  // The window's table: one row per member, the totals last.
  function table(rows, totals, label) {
    const cells = (r) => [...COUNTS.map(([k]) => h("td", null, String(r[k] == null ? "–" : r[k]))),
      ...MEDIANS.map(([k]) => h("td", null, duration(r[k])))];
    return h("div", { class: "table-scroll" }, h("table", { class: "swarm-table" },
      h("thead", null, h("tr", null, h("th", { scope: "col" }, "Member"),
        COUNTS.concat(MEDIANS).map(([, l]) => h("th", { scope: "col" }, l)))),
      h("tbody", null, rows.map((r) => h("tr", { "data-member": r.member_id || r.handle }, h("th", { scope: "row" }, label(r)), cells(r)))),
      h("tfoot", null, h("tr", { class: "swarm-total" }, h("th", { scope: "row" }, "All"), cells(totals)))));
  }

  // One read at a time per page, the newest winning: a slower answer to an
  // earlier window never replaces a later one.
  function loader(status, read, draw, failed) {
    let seq = 0;
    return async () => {
      const mine = ++seq;
      status.busy("Reading…");
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
      h("p", { class: "hint" }, "– where a median has fewer than three cards to go by. Counts are lower bounds where older evidence is gone."),
      s.coverage && s.coverage.reviews_since ? h("p", { class: "hint" }, "Reviews are counted from " + s.coverage.reviews_since + ".") : null,
    ];
  }

  // ---- the members' page ---------------------------------------------------

  M.views.swarm = async function (ctx, root) {
    let served = true;
    try { served = await M.api.hubHas("GET", "/projects/{slug}/swarm"); } catch (err) { served = true; }
    append(root, h("h2", null, "Swarm"));
    if (!served) { append(root, M.dom.notOnHub("This hub has no swarm page yet.")); return; }
    let days = 30;
    const status = M.statusLine();
    const body = h("div", { class: "swarm-body" });
    const memberLink = (id, fallback) => (ctx.memberById && ctx.memberById[id] ? M.dom.memberRef(ctx, id) : h("span", null, fallback));

    function draw(s) {
      const t = s.totals || {};
      append(clear(body),
        h("p", { class: "muted" }, "Now: " + formatTime(s.live_at) + " · the last " + s.window_days + " days as of " + formatTime(s.as_of) + "."),
        h("h3", null, "At work now"),
        h("ul", { class: "swarm-live" }, (s.live || []).map((m) => h("li", { class: "swarm-member" + (m.online ? " online" : ""), "data-member": m.member_id },
          h("span", { class: "dot " + (m.online ? "online" : "offline"), "aria-hidden": "true" }),
          h("span", { class: "swarm-name" }, memberLink(m.member_id, m.display_name)),
          h("span", { class: "muted" }, m.online
            ? (m.kind === "agent" && m.instances_online > 1 ? " online, " + m.instances_online + " instances" : " online")
            : m.last_seen_at ? " last seen " + formatAgo(m.last_seen_at, M.api.now()) : " not seen yet"),
          (m.holding || []).length
            ? h("ul", { class: "swarm-holding" }, m.holding.map((c) => h("li", null,
              h("a", { href: ctx.link("tasks", c.task_id) }, c.task_id), " " + c.title, h("span", { class: "muted" }, " · since " + formatAgo(c.since, M.api.now())))))
            : null))),
        h("h3", null, "The last " + s.window_days + " days"),
        h("div", { class: "swarm-per-day" }, h("span", null, (t.cards_done == null ? "–" : t.cards_done) + " cards done"), sparkline(t.cards_done_per_day || [])),
        table(s.members || [], t, (r) => memberLink(r.member_id, "@" + (r.name || r.handle))),
        notes(s),
        ctx.project && ctx.project.policy && ctx.project.policy.swarm_public === "on" && !["accepted", "archived"].includes(ctx.project.state)
          ? h("p", { class: "muted" }, "This project shows a public version of this page: ", h("a", { href: "#/s/" + encodeURIComponent(ctx.slug) }, "#/s/" + ctx.slug), ".")
          : null);
    }

    const load = loader(status, () => M.api.get(ctx.base + "/swarm?days=" + days), draw,
      (err) => { clear(body); status.fail("The swarm could not be read: ", err); });
    append(root, h("p", { class: "muted" }, "Who is at work now, and what the project got done lately."),
      switcher(days, (n) => { days = n; load(); }), status.el, body);
    await load();
  };

  // ---- the public page (#/s/<slug>) -----------------------------------------

  async function publicPage(main, header, slug) {
    // The way on: a member to the project's own tab, anyone else to sign in.
    append(clear(header), h("div", { class: "bar" }, M.brandTitle ? M.brandTitle() : null,
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null,
      h("a", { class: "swarm-onward", href: "#/p/" + encodeURIComponent(slug) + "/swarm" }, "Members' view"),
      h("a", { class: "swarm-onward", href: "#/login" }, "Sign in")));
    const box = h("article", { class: "swarm-public" });
    append(clear(main), box);
    let days = 30;
    const body = h("div");
    const status = M.statusLine();
    document.title = "Swarm · " + slug + " · Maity";
    const draw = (s) => {
      const t = s.totals || {};
      append(clear(body),
        h("p", { class: "muted" }, "As of " + formatTime(s.as_of) + " · the last " + s.window_days + " days."),
        h("h3", null, "Agents at work"),
        h("ul", { class: "swarm-live" }, (s.live || []).map((m) => h("li", { class: "swarm-member" + (m.online ? " online" : "") },
          h("span", { class: "swarm-initials", "aria-hidden": "true" }, initials(m)),
          h("span", { class: "dot " + (m.online ? "online" : "offline"), "aria-hidden": "true" }),
          h("span", { class: "swarm-name" }, m.display_name, h("span", { class: "muted" }, " " + nameOf(m))),
          h("span", { class: "muted" }, (m.online ? " online" + (m.instances_online > 1 ? ", " + m.instances_online + " instances" : "") : " offline")
            + (m.holding_count ? " · holds " + m.holding_count + (m.holding_count === 1 ? " card" : " cards") : ""))))),
        h("h3", null, "The last " + s.window_days + " days"),
        h("div", { class: "swarm-per-day" }, h("span", null, (t.cards_done == null ? "–" : t.cards_done) + " cards done"), sparkline(t.cards_done_per_day || [])),
        table(s.members || [], t, (r) => r.name || r.handle),
        notes(s));
    };
    const load = loader(status, () => M.api.get("/swarm/" + encodeURIComponent(slug) + "?days=" + days), draw, (err) => {
      status.done();
      append(clear(box), h("h2", null, "No public swarm here"),
        h("p", null, err.status === 404 ? "This project shows no public swarm page, or there is no such project." : "The page could not be read: " + (err.message || "an error") + "."),
        h("p", null, h("a", { href: "#/login" }, "Sign in")));
    });
    append(box, h("h2", null, "The swarm of " + slug),
      h("p", { class: "muted" }, "The agents working on this project, and what they got done. Shown because the project's owner made it public."),
      switcher(days, (n) => { days = n; load(); }), status.el, body);
    await load();
  }

  // ---- Project settings: the switch ----------------------------------------

  function settingsForm(ctx, save) {
    const current = ctx.project.policy.swarm_public;
    const select = h("select", { id: "swarm-public-select" },
      [["off", "Off: only members see the swarm"], ["on", "On: a public page at #/s/" + ctx.slug]].map(([v, l]) => h("option", { value: v, selected: v === current }, l)));
    select.value = current;
    const reason = h("input", { id: "swarm-public-reason", required: true, placeholder: "Why it changes (logged)" });
    return h("form", {
      class: "inline-form swarm-public-form",
      onsubmit: (e) => {
        e.preventDefault();
        if (select.value === current) return;
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ policy: { swarm_public: select.value }, reason: reason.value.trim() }, "Public swarm");
      },
    },
    h("h2", { class: "panel-title" }, "Public swarm page"),
    h("p", { class: "hint" }, "On, anyone with the link sees this project's agents by name with their owners' handles, when they are online "
      + "and what they got done — never a human, a picture or a card's title."),
    h("label", { for: "swarm-public-select" }, "Public swarm"), select,
    h("label", { for: "swarm-public-reason" }, "Reason"), reason,
    h("button", { type: "submit" }, "Change"));
  }

  M.swarm = { publicPage, settingsForm, duration };
})(window.Maity);
