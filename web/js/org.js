// The organigram, the Organisation tab of the Team page
// (/<owner>/<slug>/organisation; the maintainer, 2026-10-30; it was a
// section of the Overview): an indented tree computed from reports_to and
// area ownership on every render; nothing chart-shaped is stored or fetched.
// Its second face, Paths, is js/paths.js.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // "/" contains everything; "hub/" contains "hub/api/".
  function contains(outer, inner) {
    if (outer === inner) return false;
    if (outer === "/") return true;
    return inner.startsWith(outer.endsWith("/") ? outer : outer + "/");
  }

  // The member owning the narrowest area that contains one of m's areas.
  function areaParent(m, members) {
    let best = null;
    let bestLen = -1;
    members.forEach((other) => {
      if (other.id === m.id) return;
      other.areas.forEach((outer) => {
        if (m.areas.some((inner) => contains(outer, inner)) && outer.length > bestLen) {
          best = other;
          bestLen = outer.length;
        }
      });
    });
    return best;
  }

  function buildTree(members) {
    const byId = {};
    members.forEach((m) => { byId[m.id] = m; });
    const parentOf = {};
    members.forEach((m) => {
      if (m.reports_to && byId[m.reports_to]) {
        parentOf[m.id] = { id: m.reports_to, via: "reports_to" };
      } else {
        const p = areaParent(m, members);
        if (p) parentOf[m.id] = { id: p.id, via: "area" };
      }
    });
    // A cycle in the data would hang the recursion; break it at the member
    // where it is found and show that member as a root.
    const roots = [];
    members.forEach((m) => {
      const seen = new Set([m.id]);
      let cur = parentOf[m.id];
      while (cur) {
        if (seen.has(cur.id)) { delete parentOf[m.id]; break; }
        seen.add(cur.id);
        cur = parentOf[cur.id];
      }
      if (!parentOf[m.id]) roots.push(m);
    });
    const children = {};
    members.forEach((m) => {
      const p = parentOf[m.id];
      if (p) (children[p.id] = children[p.id] || []).push(m);
    });
    return { roots, children, parentOf };
  }

  // An agent's live instances, each a link to its Sessions on the member's page, as an
  // instance is everywhere else (the maintainer, 2026-11-01). A dormant one answers only
  // its own address (§6.17), and says so beside its link.
  function instances(ctx, m) {
    const live = (m.instances || []).filter((i) => !i.revoked_at);
    if (m.kind !== "agent" || !live.length) return null;
    const handle = M.dom.handleOf(ctx, m) || m.handle || m.id;
    return h("span", { class: "org-instances" }, live.map((i) => h("span", { class: "org-instance" },
      h("a", { class: "member-instance", href: M.dom.instanceHref(ctx, m.id, i.id),
        "aria-label": M.t("org.instance.label", { address: "@" + handle + "#" + i.id }) }, "#" + i.id),
      i.dormant ? h("span", { class: "muted member-dormant" }, " " + M.dom.dormantNote(ctx, m, i)) : null)));
  }

  // Who is below a lead, from the hub's `manages` (§6.2), never counted here: the direct
  // reports with their instances, and the whole branch on hover when it is larger.
  function manages(m) {
    const direct = M.dom.managesText(m.manages, "direct");
    if (!direct) return null;
    const total = m.manages.total.members > m.manages.direct.members ? M.dom.managesText(m.manages, "total") : null;
    return h("span", { class: "muted org-manages", title: total ? M.t("manages.total", { text: total }) : null }, direct);
  }

  function node(ctx, m, tree) {
    const kids = tree.children[m.id] || [];
    const link = tree.parentOf[m.id];
    return h("li", null,
      h("div", { class: "org-node" },
        h("span", { class: "dot " + (m.kind === "human" ? "human" : m.presence), "aria-hidden": "true" }),
        M.avatar(m, 20),
        h("strong", null, M.dom.memberRef(ctx, m.id)),
        h("span", { class: "role" }, M.trust.words(m)),
        m.areas.length ? h("span", { class: "area" }, m.areas.join(", ")) : null,
        link && link.via === "area" ? h("span", { class: "muted" }, M.t("org.by_area")) : null,
        instances(ctx, m),
        manages(m)),
      kids.length ? h("ul", null, kids.map((k) => node(ctx, k, tree))) : null);
  }

  // The top follows trust (the maintainer, 2026-10-31): whoever has no place
  // by reports_to or area stands at their trust's level, owners at the top,
  // then admins, members and guests, each a level deeper; a level nobody holds
  // leaves no empty step. Not under one owner's node: with several owners that
  // would claim a line to one of them that the project does not have.
  function drawTree(ctx) {
    const tree = buildTree(ctx.members || []);
    if (!tree.roots.length) return h("p", { class: "muted" }, M.t("org.empty"));
    const tier = (t) => tree.roots.filter((m) => (M.trust.TRUSTS.includes(m.trust) ? m.trust : "member") === t);
    const levels = M.trust.TRUSTS.map(tier).filter((list) => list.length);
    // From the deepest up: each level's members, the deeper levels in one item under them.
    let deeper = null;
    for (let i = levels.length - 1; i > 0; i--) {
      deeper = h("li", { class: "org-level" }, h("ul", null, levels[i].map((m) => node(ctx, m, tree)), deeper));
    }
    return h("ul", { class: "org-tree" }, levels[0].map((m) => node(ctx, m, tree)), deeper);
  }

  // One's own fleet, the Organisation tab of a project's Agents (tsk-q989pagmk2x9; the maintainer,
  // 2026-11-02): the same tree, built from one's own agents here alone, under oneself. An agent
  // that reports to someone else's shows that as a stub, and nothing more of the other side.
  const live = (m) => (m.instances || []).filter((i) => !i.revoked_at);

  const STATE_WORDS = {
    online: () => M.t("chat.presence.online"), away: () => M.t("chat.presence.away"),
    offline: () => M.t("chat.presence.offline"), dormant: () => M.t("org.fleet.dormant"),
  };
  // An instance as a dot in its presence's colour, the lead ringed, a link to its sessions.
  function fleetDots(ctx, m) {
    const handle = M.dom.handleOf(ctx, m) || m.handle || m.id;
    const list = live(m);
    if (!list.length) return h("span", { class: "muted fleet-none" }, M.t("org.fleet.no_instances"));
    return h("span", { class: "fleet-dots" }, list.map((i) => {
      const state = i.dormant ? "dormant" : (i.presence || "offline");
      const words = [Object.hasOwn(STATE_WORDS, state) ? STATE_WORDS[state]() : state];
      if (i.lead) words.push(M.t("org.fleet.lead"));
      return h("a", { class: "fleet-dot " + state + (i.lead ? " lead" : ""), href: M.dom.instanceHref(ctx, m.id, i.id),
        "aria-label": M.t("org.fleet.dot", { address: "@" + handle + "#" + i.id, state: words.join(", ") }),
        title: "#" + i.id + " · " + words.join(", ") });
    }));
  }

  // Someone else's boss by its handle alone, as text: no link to their page, no name, no tooltip
  // (the card: "reports to @x", nothing more of the other side). Where the list gives no handle,
  // a neutral sentence, never its id or a name.
  function bossStub(ctx, id) {
    const m = ctx.memberById ? ctx.memberById[id] : null;
    const handle = m ? M.dom.handleOf(ctx, m) || m.handle : null;
    return handle ? M.t("org.fleet.reports_to", { who: "@" + handle }) : M.t("org.fleet.reports_to_someone");
  }

  function fleetNode(ctx, m, tree, own, byId) {
    const kids = tree.children[m.id] || [];
    const claims = live(m).reduce((n, i) => n + (i.claims || 0), 0);
    const boss = m.reports_to && !own.has(m.reports_to) && m.reports_to !== ctx.me.id ? m.reports_to : null;
    return h("li", { class: "fleet-member", "data-member": m.id },
      h("div", { class: "org-node fleet-node" },
        M.avatar(m, 20),
        h("strong", null, M.dom.memberRef(ctx, m.id)),
        m.areas.length ? h("span", { class: "area" }, m.areas.join(", ")) : null,
        fleetDots(ctx, m),
        h("span", { class: "muted fleet-claims" }, M.t("org.fleet.claims", { count: claims }))),
      boss ? h("p", { class: "fleet-stub" }, bossStub(ctx, boss)) : null,
      kids.length ? h("ul", null, kids.map((k) => fleetNode(ctx, byId[k.id], tree, own, byId))) : null);
  }

  function drawFleet(ctx) {
    const mine = (ctx.members || []).filter((m) => m.kind === "agent" && m.owner_id === ctx.me.id && !m.removed_at);
    if (!mine.length) return h("p", { class: "muted fleet-empty" }, M.t("org.fleet.empty"));
    // Built from one's own agents alone: a boss or an area owner of someone else's places nobody
    // here (buildTree follows a reports_to only to a member it was given).
    const tree = buildTree(mine);
    const own = new Set(mine.map((m) => m.id));
    const byId = Object.fromEntries(mine.map((m) => [m.id, m]));
    const me = (ctx.members || []).find((m) => m.id === ctx.me.id) || ctx.me;
    return h("ul", { class: "org-tree fleet-tree" }, h("li", { class: "fleet-member", "data-member": ctx.me.id },
      h("div", { class: "org-node fleet-node fleet-me" }, M.avatar(me, 20), h("strong", null, M.dom.memberRef(ctx, ctx.me.id))),
      h("ul", null, tree.roots.map((r) => fleetNode(ctx, byId[r.id], tree, own, byId)))));
  }

  // Tree or Paths (js/paths.js), kept per browser like the other per-reader choices; a
  // browser that keeps nothing starts at the tree.
  const FACE = "maity.org.face";
  function storedFace() {
    try { return window.localStorage.getItem(FACE) === "paths" ? "paths" : "tree"; } catch { return "tree"; }
  }
  function keepFace(face) {
    try { window.localStorage.setItem(FACE, face); } catch { /* the tab still switches */ }
  }

  // The tab: the tree or the paths, drawn again from the members when one changes. The paths'
  // chip, selection and opened columns stay across that redraw.
  M.views.organisation = async function (ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "org-box" });
    const paths = { chip: null, selected: null, open: new Set() };
    let face = storedFace();
    const faces = h("div", { class: "org-faces", role: "group", "aria-label": M.t("org.face.label") });
    const draw = () => {
      const nextFaces = h("div");
      append(nextFaces, ["tree", "paths"].map((f) => h("button", { type: "button", class: "org-face",
        "data-face": f, "aria-pressed": face === f ? "true" : "false",
        onclick: () => { if (face === f) return; face = f; keepFace(f); draw(); } }, (f === "paths" ? M.t("org.face.paths") : M.t("org.face.tree")))));
      const fresh = face === "paths" ? M.paths.draw(ctx, paths) : drawTree(ctx);
      M.dom.keepImages(faces, nextFaces);
      M.dom.keepImages(box, fresh);
      append(clear(faces), Array.from(nextFaces.childNodes));
      append(clear(box), fresh);
    };
    append(root, M.teamTabs(ctx, "organisation"), h("h2", null, M.t("team.tab.organisation")),
      h("p", { class: "muted" }, M.t("org.intro", { preset: ctx.project.policy.preset })), faces, status.el, box);
    draw();
    ctx.onEvents((events) => {
      if (!events.some((e) => /^member_/.test(e.kind))) return;
      M.api.getAll(ctx.base + "/members").then((r) => { M.withMembers(ctx, r.items); draw(); status.done(); },
        (err) => status.fail(M.t("org.reread_failed"), err));
    });
  };

  M.org = { buildTree, drawTree, drawFleet, contains };
})(window.Maity);
