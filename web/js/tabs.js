// The project tabs in the header (docs/api.md §5.1 "Start tabs"): which of
// the human's projects this browser shows as tabs, and in which order. They
// are this browser's own, kept per viewer in localStorage (every access in
// try/catch: without storage they hold for the visit) and never sent, so two
// devices may show different tabs (the maintainer, req-6zp8zjwabmds). The
// account's `start_tabs` only seeds a browser that has none yet. Projects are
// named by their fixed id, so a rename or a transfer keeps the tab.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const key = (me) => "maity.tabs." + me.id;
  const filterKey = (me) => "maity.inbox.tabs." + me.id;
  // A browser that keeps nothing still keeps the tabs for this visit.
  const kept = {};

  function read(me) {
    let raw;
    try { raw = window.localStorage.getItem(key(me)); } catch (err) { return kept[me.id] || null; }
    try {
      const value = raw ? JSON.parse(raw) : null;
      if (value && Array.isArray(value.open) && Array.isArray(value.known)) return value;
    } catch (err) { /* not ours: start again */ }
    return null;
  }
  function write(me, value) {
    kept[me.id] = value;
    try { window.localStorage.setItem(key(me), JSON.stringify(value)); } catch (err) { /* this browser keeps nothing */ }
  }

  // Tabs make sense for a human with projects; an agent's one project stays as it is.
  const managed = (ctx) => ctx.me && ctx.me.kind === "human";

  // The state as it holds now: `open` in tab order, `known` the projects
  // this browser has seen. A project the human joined since is not known
  // yet and opens as the last tab; one they left drops out of both.
  function state(ctx) {
    const ids = ctx.projects.map((p) => p.id);
    const before = read(ctx.me);
    let now;
    if (!before) {
      const start = ctx.me.start_tabs;
      now = { open: Array.isArray(start) ? start.filter((id) => ids.includes(id)) : ids.slice(), known: ids.slice() };
    } else {
      const open = before.open.filter((id) => ids.includes(id));
      ids.forEach((id) => { if (!before.known.includes(id) && !open.includes(id)) open.push(id); });
      now = { open, known: ids.slice() };
    }
    if (!before || JSON.stringify(before) !== JSON.stringify(now)) write(ctx.me, now);
    return now;
  }

  // The projects shown as tabs, in order.
  function open(ctx) {
    if (!managed(ctx)) return ctx.projects;
    const byId = new Map(ctx.projects.map((p) => [p.id, p]));
    return state(ctx).open.map((id) => byId.get(id)).filter(Boolean);
  }
  const isOpen = (ctx, id) => !managed(ctx) || state(ctx).open.includes(id);

  function setOpen(ctx, id, on) {
    const s = state(ctx);
    const rest = s.open.filter((x) => x !== id);
    write(ctx.me, { open: on ? (s.open.includes(id) ? s.open : rest.concat(id)) : rest, known: s.known });
  }

  // Moves a tab by `step` places (the keyboard, the menu), or before
  // `beforeId` (a drop; null puts it last). Says whether it moved.
  function move(ctx, id, step) {
    const s = state(ctx);
    const at = s.open.indexOf(id);
    const to = at + step;
    if (at < 0 || to < 0 || to >= s.open.length) return false;
    const order = s.open.slice();
    order.splice(at, 1);
    order.splice(to, 0, id);
    write(ctx.me, { open: order, known: s.known });
    return true;
  }
  function moveBefore(ctx, id, beforeId) {
    const s = state(ctx);
    if (!s.open.includes(id) || id === beforeId) return false;
    const order = s.open.filter((x) => x !== id);
    const at = beforeId ? order.indexOf(beforeId) : -1;
    order.splice(at < 0 ? order.length : at, 0, id);
    if (order.join() === s.open.join()) return false;
    write(ctx.me, { open: order, known: s.known });
    return true;
  }

  // The account's start set (§5.1): `null` opens every membership.
  const inStart = (ctx, id) => !Array.isArray(ctx.me.start_tabs) || ctx.me.start_tabs.includes(id);
  async function saveStart(ctx, list) {
    const answer = await M.api.patch("/me", { start_tabs: list });
    ctx.me.start_tabs = answer && answer.member ? answer.member.start_tabs : list;
    return ctx.me.start_tabs;
  }
  // One project in or out of the start set, from its own settings (Mine).
  // Out of a `null` set: every other membership, in the order of `/me`.
  function startWith(ctx, id, on) {
    const ids = ctx.projects.map((p) => p.id);
    const now = Array.isArray(ctx.me.start_tabs) ? ctx.me.start_tabs.filter((x) => ids.includes(x)) : ids.slice();
    const rest = now.filter((x) => x !== id);
    return saveStart(ctx, on ? (now.includes(id) ? now : rest.concat(id)) : rest);
  }
  // The tab row as it is, as the start set.
  const keepAsStart = (ctx) => saveStart(ctx, state(ctx).open.slice());

  // The cross-project inbox's filter to projects with an open tab, kept per
  // viewer in this browser like the tabs.
  function onlyOpen(me) {
    try { return window.localStorage.getItem(filterKey(me)) === "1"; } catch (err) { return !!kept["inbox." + me.id]; }
  }
  function setOnlyOpen(me, on) {
    kept["inbox." + me.id] = on;
    try { if (on) window.localStorage.setItem(filterKey(me), "1"); else window.localStorage.removeItem(filterKey(me)); } catch (err) { /* this browser keeps nothing */ }
  }

  M.tabs = { open, isOpen, setOpen, move, moveBefore, inStart, startWith, keepAsStart, onlyOpen, setOnlyOpen, managed };
})(window.Maity);
