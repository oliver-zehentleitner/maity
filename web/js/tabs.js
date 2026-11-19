// The project tabs in the header (docs/api.md §5.1 "Start tabs"): which of
// the human's projects this browser shows as tabs, and in which order. They
// are this browser's own, kept per viewer in localStorage (every access in
// try/catch: without storage they hold for the visit) and never sent, so two
// devices may show different tabs (the maintainer, req-6zp8zjwabmds). The
// account's `start_tabs` only seeds a browser that has none yet. Projects are
// named by their fixed id, so a rename or a transfer keeps the tab.
//
// A public project the human is no member of is a tab too, drawn dashed
// (§5.1 "Stars", §6.30 Q2; web/context/views.md): one opened in this browser
// session is kept in sessionStorage until it is closed or the session ends,
// and is never sent; a starred one (`/me` `starred`) joins the tabs above,
// after `start_tabs` in a browser that has none yet.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const key = (me) => "maity.tabs." + me.id;
  const filterKey = (me) => "maity.inbox.tabs." + me.id;
  const outsiderKey = (me) => "maity.tabs.outsider." + me.id;
  // A browser that keeps nothing still keeps the tabs for this visit. Once a
  // write failed (a full store that still reads), the store holds an older
  // value: until a write of that key succeeds again (tried at each read), this
  // visit reads what it kept here, not the store.
  const kept = {};
  const unwritten = new Set();
  // `area` is localStorage, or sessionStorage for the outsider's tabs.
  function store(k, value, area) {
    try {
      const s = window[area || "localStorage"];
      if (value === null) s.removeItem(k); else s.setItem(k, value);
      unwritten.delete(k);
    } catch (err) { unwritten.add(k); }
  }

  // A key whose last write failed: write what this visit holds again; false
  // while the store still refuses it, so the caller reads from memory.
  function healed(k, value, area) {
    if (!unwritten.has(k)) return true;
    store(k, value, area);
    return !unwritten.has(k);
  }

  function read(me) {
    if (!healed(key(me), kept[me.id] ? JSON.stringify(kept[me.id]) : null)) return kept[me.id] || null;
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
    store(key(me), JSON.stringify(value));
  }

  // This session's outsider tabs, in the order opened: `[{full_name, name}]`, named by the full
  // name, since the public page a non-member reads carries no project id (docs/api.md §16.9).
  const sessionKept = (me) => "outsider." + me.id;
  function readOutsiders(me) {
    const mem = kept[sessionKept(me)] || [];
    if (!healed(outsiderKey(me), mem.length ? JSON.stringify(mem) : null, "sessionStorage")) return mem.slice();
    let raw;
    try { raw = window.sessionStorage.getItem(outsiderKey(me)); } catch (err) { return mem.slice(); }
    try {
      const value = raw ? JSON.parse(raw) : [];
      if (Array.isArray(value)) return value.filter((t) => t && typeof t.full_name === "string");
    } catch (err) { /* not ours: none */ }
    return [];
  }
  function writeOutsiders(me, list) {
    kept[sessionKept(me)] = list;
    store(outsiderKey(me), list.length ? JSON.stringify(list) : null, "sessionStorage");
  }

  // Tabs make sense for a human with projects; an agent's one project stays as it is.
  const managed = (ctx) => ctx.me && ctx.me.kind === "human";

  // A dashed tab's name: the project's own where the page read gave it, else its full name
  // (`/me` `starred` carries only `{id, full_name}`).
  const outsiderRow = (t, starred) => ({ id: t.id || null, full_name: t.full_name, name: t.name || t.full_name, outsider: true, starred });
  // The starred projects as `/me` has them, without one that became a membership meanwhile.
  function starredRows(ctx) {
    const list = Array.isArray(ctx.me.starred) ? ctx.me.starred : [];
    const mine = new Set(ctx.projects.map((p) => p.id));
    return list.filter((s) => s && s.id && !mine.has(s.id) && !ctx.projects.some((p) => p.full_name === s.full_name))
      .map((s) => outsiderRow(s, true));
  }

  // The state as it holds now: `open` in tab order, `known` the projects
  // this browser has seen. A project the human joined or starred since is
  // not known yet and opens as the last tab; one they left or unstarred drops
  // out of both. A browser with nothing kept opens `start_tabs`, then the
  // starred projects (§5.1).
  function state(ctx) {
    const members = ctx.projects.map((p) => p.id);
    const ids = members.concat(starredRows(ctx).map((s) => s.id));
    const before = read(ctx.me);
    let now;
    if (!before) {
      const start = ctx.me.start_tabs;
      const first = Array.isArray(start) ? start.filter((id) => members.includes(id)) : members.slice();
      now = { open: first.concat(ids.filter((id) => !members.includes(id))), known: ids.slice() };
    } else {
      const open = before.open.filter((id) => ids.includes(id));
      ids.forEach((id) => { if (!before.known.includes(id) && !open.includes(id)) open.push(id); });
      now = { open, known: ids.slice() };
    }
    if (!before || JSON.stringify(before) !== JSON.stringify(now)) write(ctx.me, now);
    return now;
  }

  // The member projects shown as tabs, in order: what the inbox's filter and grouping follow.
  function open(ctx) {
    if (!managed(ctx)) return ctx.projects;
    const byId = new Map(ctx.projects.map((p) => [p.id, p]));
    return state(ctx).open.map((id) => byId.get(id)).filter(Boolean);
  }
  // Every tab of the row, in order: the member and starred tabs as this browser keeps them,
  // then this session's outsider tabs that are neither.
  function row(ctx) {
    if (!managed(ctx)) return ctx.projects;
    const starred = starredRows(ctx);
    const byId = new Map(ctx.projects.concat(starred).map((p) => [p.id, p]));
    const tabs = state(ctx).open.map((id) => byId.get(id)).filter(Boolean);
    const taken = (full) => ctx.projects.some((p) => p.full_name === full) || starred.some((s) => s.full_name === full);
    return tabs.concat(readOutsiders(ctx.me).filter((t) => !taken(t.full_name)).map((t) => outsiderRow(t, false)));
  }
  // The starred projects whose tab is closed in this browser (the tabs menu opens them again).
  function starredClosed(ctx) {
    if (!managed(ctx)) return [];
    const s = state(ctx);
    return starredRows(ctx).filter((p) => !s.open.includes(p.id));
  }
  const isOpen = (ctx, id) => !managed(ctx) || state(ctx).open.includes(id);

  function setOpen(ctx, id, on) {
    const s = state(ctx);
    const rest = s.open.filter((x) => x !== id);
    write(ctx.me, { open: on ? (s.open.includes(id) ? s.open : rest.concat(id)) : rest, known: s.known });
  }

  // A public project opened by a human who is no member (app.js, the visiting path): its
  // starred tab opens again where it is closed, else it is a tab for this session, last.
  function visit(ctx, project) {
    if (!managed(ctx) || !project || ctx.projects.some((p) => p.full_name === project.full_name)) return;
    const starred = starredRows(ctx).find((s) => s.full_name === project.full_name);
    if (starred) {
      if (!isOpen(ctx, starred.id)) setOpen(ctx, starred.id, true);
      return;
    }
    const list = readOutsiders(ctx.me);
    const at = list.findIndex((t) => t.full_name === project.full_name);
    if (at < 0) writeOutsiders(ctx.me, list.concat({ full_name: project.full_name, name: project.name || null }));
    else if (project.name && list[at].name !== project.name) {
      list[at] = { full_name: project.full_name, name: project.name };
      writeOutsiders(ctx.me, list);
    }
  }
  // Closes this session's tab of a project (the tabs menu); nothing is sent.
  function closeOutsider(ctx, full) {
    writeOutsiders(ctx.me, readOutsiders(ctx.me).filter((t) => t.full_name !== full));
  }

  // Takes the star off (§5.1): `starred` again whole, without the project, the rest in its
  // order. The tab stays as this session's own until it is closed. A refusal leaves both.
  async function unstar(ctx, row) {
    const list = (Array.isArray(ctx.me.starred) ? ctx.me.starred : []).map((s) => s.id).filter((id) => id !== row.id);
    const answer = await M.api.patch("/me", { starred: list });
    const now = answer && answer.member && Array.isArray(answer.member.starred) ? answer.member.starred
      : ctx.me.starred.filter((s) => s.id !== row.id);
    const outsiders = readOutsiders(ctx.me);
    if (!outsiders.some((t) => t.full_name === row.full_name)) {
      writeOutsiders(ctx.me, outsiders.concat({ full_name: row.full_name, name: row.name !== row.full_name ? row.name : null }));
    }
    ctx.me.starred = now;
    return now;
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
  // The tab row as it is, as the start set: its memberships, since `start_tabs` names only
  // those (§5.1); the starred tabs open after them anyway.
  const keepAsStart = (ctx) => saveStart(ctx, open(ctx).map((p) => p.id));

  // The cross-project inbox's filter to projects with an open tab, kept per
  // viewer in this browser like the tabs.
  function onlyOpen(me) {
    if (!healed(filterKey(me), kept["inbox." + me.id] ? "1" : null)) return !!kept["inbox." + me.id];
    try { return window.localStorage.getItem(filterKey(me)) === "1"; } catch (err) { return !!kept["inbox." + me.id]; }
  }
  function setOnlyOpen(me, on) {
    kept["inbox." + me.id] = on;
    store(filterKey(me), on ? "1" : null);
  }

  M.tabs = { open, row, starredClosed, isOpen, setOpen, visit, closeOutsider, unstar, move, moveBefore, inStart, startWith, keepAsStart, onlyOpen, setOnlyOpen, managed };
})(window.Maity);
