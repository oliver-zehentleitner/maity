// Paths, the second face of the Organisation tab (tsk-j9ktmj7e4fxq, gj6k's draft): who talks
// to whom. The members stand top down along the reporting lines, a lead above the members that
// report to it, and more than GROUP_AT members of one role under one lead fold into one box.
// Grey lines say who reports to whom, the selected member's in the accent colour, and a chip
// draws one event's route as orange dashed arrows. Everything is computed from the members
// (§6.2) on every render, as the tree is; nothing is stored or fetched. The routes are a small
// fixed table here that follows docs/api.md §8.2 and §8.4, and every edge it draws comes from
// a field of the member view: `reports_to`, `owner_id`, `role`, `trust`. Where the hub's rule
// depends on the card (who assigns it, who wrote it), the view draws the usual route, marks
// those edges as usual and says so in the legend (lotse, req-x3hgj0b7xzy3).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  // More members of one role under one lead than this stand as one box until it is opened.
  const GROUP_AT = 6;
  const NODE_W = 104;
  const NODE_H = 96;
  const GROUP_W = 196;
  const GROUP_H = 104;
  const GAP = 10;
  const ROW_H = 160;
  // Room above the first row for a route between two members of one row, which bows upwards.
  const PAD = 56;
  const CHIPS = ["review_result", "not_listening", "request_human", "card_assigned"];
  // Each chip's name and its note, keys written out so tools/check.py finds them.
  const CHIP_NAME = {
    review_result: () => M.t("paths.chip.review_result"),
    not_listening: () => M.t("paths.chip.not_listening"),
    request_human: () => M.t("paths.chip.request_human"),
    card_assigned: () => M.t("paths.chip.card_assigned"),
  };
  const CHIP_NOTE = {
    review_result: () => M.t("paths.route.note.review_result"),
    not_listening: () => M.t("paths.route.note.not_listening"),
    request_human: () => M.t("paths.route.note.request_human"),
    card_assigned: () => M.t("paths.route.note.card_assigned"),
  };

  const isAgent = (m) => m.kind === "agent";

  // The route of one chip as edges {from, to, usual}: `usual` where the hub's rule depends on
  // the card and the edge is the common case, not something the member view says.
  function routes(chip, members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    const lead = (m) => (m.reports_to && byId[m.reports_to] ? m.reports_to : null);
    const owner = (m) => (isAgent(m) && m.owner_id && byId[m.owner_id] ? m.owner_id : null);
    const out = [];
    const seen = new Set();
    const add = (from, to, usual) => {
      if (!from || !to || from === to) return;
      const key = from + ">" + to;
      if (seen.has(key)) return;
      seen.add(key);
      out.push({ from, to, usual: !!usual });
    };
    if (chip === "review_result") {
      // §8.4: the hub adds the sender's reports_to; the author and the author's lead hang
      // on the card, so the legend names them and no edge does.
      members.filter((m) => M.trust.roleIs(m, "reviewer")).forEach((m) => add(m.id, lead(m)));
    } else if (chip === "not_listening") {
      // §8.2 member_not_listening: the agent's reports_to, trust:admin (never a proxy), its
      // human owner when a member.
      const admins = members.filter((m) => m.trust === "admin" && !M.trust.roleIs(m, "proxy"));
      members.filter(isAgent).forEach((m) => {
        add(m.id, lead(m));
        admins.forEach((a) => add(m.id, a.id));
        add(m.id, owner(m));
      });
    } else if (chip === "request_human") {
      // `maity ask --to human` reaches the agent's own owner (§7); 1A: the one route drawn.
      members.filter(isAgent).forEach((m) => add(m.id, owner(m)));
    } else if (chip === "card_assigned") {
      // §8.2 task_assigned reaches the assignee and its human owner; who assigns is the
      // card's, so the lead stands in as the usual sender (2A).
      members.forEach((m) => {
        const from = lead(m);
        if (!from) return;
        add(from, m.id, true);
        add(from, owner(m), true);
      });
    }
    return out;
  }

  // Grey lines: every member to the member it reports to.
  function reportLines(members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    return members.filter((m) => m.reports_to && byId[m.reports_to] && m.reports_to !== m.id)
      .map((m) => ({ from: m.id, to: m.reports_to, cross: !!m.cross_owner }));
  }

  const nameOf = (m) => m.display_name || m.handle || m.id;
  const byName = (a, b) => nameOf(a).localeCompare(nameOf(b));
  const human = (m) => m.kind === "human";

  // The reporting tree: who reports to each member, and the members that report to nobody,
  // humans first. A member in a cycle that no root reaches stands as a root of its own.
  function tree(members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    const below = {};
    const roots = [];
    members.forEach((m) => {
      if (m.reports_to && byId[m.reports_to] && m.reports_to !== m.id) (below[m.reports_to] = below[m.reports_to] || []).push(m);
      else roots.push(m);
    });
    Object.values(below).forEach((list) => list.sort(byName));
    roots.sort((a, b) => (human(a) ? 0 : 1) - (human(b) ? 0 : 1) || byName(a, b));
    const reached = new Set();
    const walk = (m) => { if (reached.has(m.id)) return; reached.add(m.id); (below[m.id] || []).forEach(walk); };
    roots.forEach(walk);
    members.slice().sort(byName).forEach((m) => { if (!reached.has(m.id)) { roots.push(m); walk(m); } });
    return { below, roots };
  }

  // Where each box stands: rows by depth, a lead centred over the boxes below it. Under one lead,
  // the members of a role with more than GROUP_AT stand as one box unless the reader opened that
  // role (`open`, a Set of roles). `boxOf` names the box a member is drawn in.
  function layout(members, open) {
    const t = tree(members);
    const at = {};
    const boxOf = {};
    const items = [];
    const groups = [];
    const placed = new Set();
    // The boxes under one item: its members' reports, one role folded where it is large.
    function under(item) {
      const kids = [];
      (item.group ? item.members : [item.member]).forEach((m) => (t.below[m.id] || []).forEach((k) => { if (!placed.has(k.id)) kids.push(k); }));
      const byRole = {};
      kids.forEach((k) => { (byRole[k.role || "member"] = byRole[k.role || "member"] || []).push(k); });
      const out = [];
      const done = new Set();
      kids.forEach((k) => {
        const role = k.role || "member";
        if (done.has(role)) return;
        if (byRole[role].length > GROUP_AT && !open.has(role)) {
          done.add(role);
          out.push({ id: "group:" + item.id + ":" + role, group: role, members: byRole[role] });
        } else {
          out.push({ id: k.id, member: k });
        }
      });
      out.forEach((o) => (o.group ? o.members : [o.member]).forEach((m) => placed.add(m.id)));
      return out;
    }
    const widthOf = (item) => (item.group ? GROUP_W : NODE_W);
    const heightOf = (item) => (item.group ? GROUP_H : NODE_H);
    // Lays out an item and the boxes under it from `left`; returns the width it took.
    function place(item, depth, left) {
      const kids = under(item);
      let x = left;
      kids.forEach((k) => { x += place(k, depth + 1, x) + GAP; });
      const kidsWidth = kids.length ? x - GAP - left : 0;
      const w = widthOf(item);
      const total = Math.max(w, kidsWidth);
      let cx = left + total / 2;
      if (kids.length) {
        const first = at[kids[0].id];
        const last = at[kids[kids.length - 1].id];
        cx = (first.x + first.w / 2 + last.x + last.w / 2) / 2;
        if (kidsWidth < w) {  // a lead wider than its reports: move them under its middle
          const shift = (w - kidsWidth) / 2;
          kids.forEach((k) => shiftTree(k, shift));
          cx += shift;
        }
      }
      at[item.id] = { x: cx - w / 2, y: PAD + depth * ROW_H, w, h: heightOf(item) };
      (item.group ? item.members : [item.member]).forEach((m) => { boxOf[m.id] = item.id; });
      items.push(item);
      if (item.group) groups.push(item);
      item.kids = kids;
      return total;
    }
    function shiftTree(item, dx) {
      at[item.id].x += dx;
      (item.kids || []).forEach((k) => shiftTree(k, dx));
    }
    let x = GAP;
    t.roots.forEach((m) => {
      if (placed.has(m.id)) return;
      placed.add(m.id);
      x += place({ id: m.id, member: m }, 0, x) + GAP * 2;
    });
    const boxes = Object.values(at);
    const width = Math.max(...boxes.map((b) => b.x + b.w)) + GAP;
    const height = Math.max(...boxes.map((b) => b.y + b.h)) + GAP;
    const roles = new Set(members.map((m) => m.role || "member"));
    const opened = [...open].filter((r) => roles.has(r) && Object.values(t.below).some((list) => list.filter((k) => (k.role || "member") === r).length > GROUP_AT));
    return { items, groups, at, boxOf, width, height, opened };
  }

  // Edges between the boxes drawn: a member inside a folded box stands for its box, and two
  // edges that land on the same pair of boxes are one.
  function onBoxes(edges, boxOf) {
    const seen = new Set();
    const out = [];
    edges.forEach((e) => {
      const from = boxOf[e.from];
      const to = boxOf[e.to];
      if (!from || !to || from === to) return;
      const key = from + ">" + to;
      if (seen.has(key)) return;
      seen.add(key);
      out.push(Object.assign({}, e, { from, to }));
    });
    return out;
  }

  function svg(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => { if (v !== null && v !== undefined) el.setAttribute(k, String(v)); });
    return el;
  }

  // A curve between two boxes: from the bottom of the upper to the top of the lower, or, in one
  // row, from top to top in an arc above them. `shift` moves both ends sideways, so a route does
  // not lie on the reporting line between the same two members.
  function curve(a, b, shift) {
    const ax = a.x + a.w / 2 + shift;
    const bx = b.x + b.w / 2 + shift;
    if (a.y === b.y) {
      const up = Math.min(PAD - 8, 24 + Math.abs(bx - ax) * 0.12);
      return ["M", ax, a.y, "C", ax, a.y - up, bx, b.y - up, bx, b.y].join(" ");
    }
    const down = b.y > a.y;
    const y1 = down ? a.y + a.h : a.y;
    const y2 = down ? b.y : b.y + b.h;
    const mid = (y1 + y2) / 2;
    return ["M", ax, y1, "C", ax, mid, bx, mid, bx, y2].join(" ");
  }

  const touches = (e, id) => e.from === id || e.to === id;

  function drawLines(place, lines, route, selected, showLines) {
    const s = svg("svg", { class: "paths-lines", width: place.width, height: place.height, "aria-hidden": "true", focusable: "false" });
    const defs = svg("defs");
    const marker = svg("marker", { id: "paths-arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
    marker.appendChild(svg("path", { d: "M0 0 L10 5 L0 10 z", class: "paths-arrow-head" }));
    defs.appendChild(marker);
    s.appendChild(defs);
    const dim = (e) => !!selected && !touches(e, selected);
    const classes = (...names) => names.filter(Boolean).join(" ");
    if (showLines) {
      lines.forEach((e) => s.appendChild(svg("path", { d: curve(place.at[e.to], place.at[e.from], 0),
        class: classes("paths-report", e.cross && "cross", dim(e) && "dim", !!selected && !dim(e) && "on"), "data-from": e.from, "data-to": e.to })));
    }
    route.forEach((e) => s.appendChild(svg("path", { d: curve(place.at[e.from], place.at[e.to], 12),
      class: classes("paths-route", e.usual && "usual", dim(e) && "dim"), "marker-end": "url(#paths-arrow)", "data-from": e.from, "data-to": e.to })));
    return s;
  }

  // An agent's live instances, the number on its square.
  const liveInstances = (m) => (m.instances || []).filter((i) => !i.revoked_at).length;

  // Sizes go through the element's style object: a style attribute as markup is refused by
  // the page's content security policy (tools/check.py).
  function sized(el, box) {
    Object.entries(box).forEach(([k, v]) => { el.style[k] = v + "px"; });
    return el;
  }

  function nodeBox(ctx, item, pos, state, linked, redraw) {
    const size = { left: pos.x, top: pos.y, width: pos.w, height: pos.h };
    const faded = state.selected && !linked.has(item.id) ? "dim" : null;
    const classes = (...names) => names.filter(Boolean).join(" ");
    if (item.group) {
      const tiles = item.members.slice(0, 24).map(() => h("span", { class: "paths-tile", "aria-hidden": "true" }));
      return sized(h("button", { type: "button", class: classes("paths-node", "paths-group", faded), "data-id": item.id, "data-role": item.group,
        "aria-expanded": "false", title: M.t("paths.group.open"), onclick: () => { state.open.add(item.group); state.selected = null; redraw(); } },
      h("span", { class: "paths-tiles" }, tiles),
      h("span", { class: "paths-group-label" }, h("strong", null, M.trust.roleLabel(item.group)), " · ", M.t("paths.group.count", { count: item.members.length }))), size);
    }
    const m = item.member;
    const count = isAgent(m) ? liveInstances(m) : 0;
    return sized(h("button", { type: "button", class: classes("paths-node", isAgent(m) ? "agent" : "human", faded, state.selected === m.id && "selected"),
      "data-id": m.id, "aria-pressed": state.selected === m.id ? "true" : "false",
      onclick: () => { state.selected = state.selected === m.id ? null : m.id; redraw(); } },
    h("span", { class: "paths-shape", "aria-hidden": "true" },
      count ? h("span", { class: "paths-count", title: M.t("paths.instances", { count }) }, String(count)) : null),
    h("span", { class: "paths-name", title: nameOf(m) }, nameOf(m)),
    h("span", { class: "paths-sub muted" }, M.trust.words(m))), size);
  }

  // "a > b · c" for each member others report to, in the order of the reporting tree: the short
  // form of the draft's panel. More than GROUP_AT of one role under one lead read as one item.
  // Who stands under one lead, as links; a role with more than GROUP_AT members there is said
  // once, as "Coder × 13", the way the drawing folds it.
  function parts(ctx, list) {
    const count = {};
    list.forEach((k) => { count[k.role || "member"] = (count[k.role || "member"] || 0) + 1; });
    const shown = new Set();
    return list.map((k) => {
      const role = k.role || "member";
      if (count[role] <= GROUP_AT) return M.dom.memberRef(ctx, k.id);
      if (shown.has(role)) return null;
      shown.add(role);
      return h("span", null, M.t("paths.glance.many", { role: M.trust.roleLabel(role), count: count[role] }));
    }).filter(Boolean);
  }

  function glance(ctx, members) {
    const t = tree(members);
    const leads = [];
    const walk = (m) => { if (leads.includes(m)) return; if (t.below[m.id]) leads.push(m); (t.below[m.id] || []).forEach(walk); };
    t.roots.forEach(walk);
    if (!leads.length) return h("p", { class: "muted" }, M.t("paths.glance.none"));
    return h("ul", { class: "paths-glance" }, leads.map((m) => h("li", null, M.dom.memberRef(ctx, m.id), " > ",
      parts(ctx, t.below[m.id]).map((x, i) => [i ? " · " : null, x]))));
  }

  function routeText(ctx, chip, route) {
    if (!chip) return h("p", { class: "muted" }, M.t("paths.route.none"));
    return h("div", null,
      h("p", null, CHIP_NOTE[chip]()),
      route.length ? h("ul", { class: "paths-route-list" }, route.map((e) => h("li", { class: e.usual ? "usual" : null },
        M.dom.memberRef(ctx, e.from), " ⇢ ", M.dom.memberRef(ctx, e.to)))) : h("p", { class: "muted" }, M.t("paths.route.empty")));
  }

  function legend() {
    const swatch = (...cls) => h("span", { class: ["paths-swatch"].concat(cls).join(" "), "aria-hidden": "true" });
    return h("div", { class: "paths-legend" },
      h("h3", null, M.t("paths.legend")),
      h("ul", null,
        h("li", null, swatch("report"), M.t("paths.legend.reports")),
        h("li", null, swatch("report", "on"), M.t("paths.legend.selected")),
        h("li", null, swatch("route"), M.t("paths.legend.route")),
        h("li", null, swatch("route", "usual"), M.t("paths.legend.usual")),
        h("li", null, swatch("human"), M.t("paths.legend.human")),
        h("li", null, swatch("agent"), M.t("paths.legend.agent"))),
      h("p", { class: "muted" }, M.t("paths.legend.rule")));
  }

  // The phone's list: one card per member, what reaches it on the chosen route.
  function list(ctx, members, chip, route) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    const t = tree(members);
    const order = [];
    const walk = (m) => { if (order.includes(m)) return; order.push(m); (t.below[m.id] || []).forEach(walk); };
    t.roots.forEach(walk);
    return h("ul", { class: "paths-list" }, order.map((m) => {
      const below = t.below[m.id] || [];
      const gets = route.filter((e) => e.to === m.id);
      return h("li", { class: "paths-card", "data-id": m.id },
        h("div", { class: "paths-card-head" }, h("span", { class: "paths-shape " + (isAgent(m) ? "agent" : "human"), "aria-hidden": "true" }),
          M.dom.memberRef(ctx, m.id), " ", h("span", { class: "muted" }, M.trust.words(m),
            isAgent(m) && liveInstances(m) ? " · " + M.t("paths.instances", { count: liveInstances(m) }) : null)),
        m.reports_to && byId[m.reports_to]
          ? h("p", null, M.tn("paths.list.reports_to", { name: M.dom.memberRef(ctx, m.reports_to) }))
          : h("p", { class: "muted" }, M.t("paths.list.top")),
        below.length ? h("p", null, "> ", parts(ctx, below).map((x, i) => [i ? " · " : null, x])) : null,
        chip && gets.length ? h("p", { class: "paths-gets" }, "⇢ ", M.tn("paths.list.gets", { event: CHIP_NAME[chip](),
          names: h("span", null, gets.map((e, i) => [i ? " · " : null, M.dom.memberRef(ctx, e.from)])) })) : null);
    }));
  }

  // The whole face: chips, the drawing with its panel, and the list for a phone; `state`
  // ({lines, chip, selected, open}) is kept by the tab across a members' redraw. The reporting
  // lines are a chip of their own, on until the reader turns them off.
  function draw(ctx, state) {
    const box = h("div", { class: "paths" });
    const redraw = () => append(clear(box), body());
    function body() {
      const members = ctx.members || [];
      if (!members.length) return h("p", { class: "muted" }, M.t("org.empty"));
      const place = layout(members, state.open);
      const route = state.chip ? routes(state.chip, members) : [];
      const lines = onBoxes(reportLines(members), place.boxOf);
      const drawn = onBoxes(route, place.boxOf);
      const linked = new Set(state.selected ? [state.selected] : []);
      if (state.selected) lines.concat(drawn).forEach((e) => { if (touches(e, state.selected)) { linked.add(e.from); linked.add(e.to); } });
      const showLines = state.lines !== false;
      const chips = h("div", { class: "paths-chips", role: "group", "aria-label": M.t("paths.chips.label") },
        h("button", { type: "button", class: "paths-chip lines", "data-chip": "lines", "aria-pressed": showLines ? "true" : "false",
          onclick: () => { state.lines = !showLines; redraw(); } }, M.t("paths.chip.lines")),
        CHIPS.map((c) => h("button", { type: "button", class: "paths-chip", "data-chip": c,
          "aria-pressed": state.chip === c ? "true" : "false",
          onclick: () => { state.chip = state.chip === c ? null : c; redraw(); } }, CHIP_NAME[c]())));
      const opened = place.opened;
      const canvas = sized(h("div", { class: "paths-canvas" },
        drawLines(place, lines, drawn, state.selected, showLines),
        place.items.map((item) => nodeBox(ctx, item, place.at[item.id], state, linked, redraw))),
      { width: place.width, height: place.height });
      const panel = h("aside", { class: "paths-panel" },
        h("section", null, h("h3", null, M.t("paths.glance")), glance(ctx, members)),
        h("section", null, h("h3", null, state.chip ? M.t("paths.route.title", { event: CHIP_NAME[state.chip]() }) : M.t("paths.route.heading")),
          routeText(ctx, state.chip, route)),
        legend());
      return [chips,
        state.selected ? h("p", null, h("button", { type: "button", class: "link-button", onclick: () => { state.selected = null; redraw(); } }, M.t("paths.selected.clear"))) : null,
        opened.length ? h("p", null, opened.map((role) => h("button", { type: "button", class: "link-button paths-fold", "data-role": role,
          onclick: () => { state.open.delete(role); state.selected = null; redraw(); } }, M.t("paths.group.close", { role: M.trust.roleLabel(role) })))) : null,
        h("div", { class: "paths-wide" }, h("div", { class: "paths-scroll" }, canvas), panel),
        h("div", { class: "paths-narrow" },
          state.chip ? h("p", { class: "muted" }, CHIP_NOTE[state.chip](), " ", M.t("paths.legend.rule")) : null,
          list(ctx, members, state.chip, route))];
    }
    redraw();
    return box;
  }

  M.paths = { routes, reportLines, layout, onBoxes, draw, CHIPS, GROUP_AT };
})(window.Maity);
