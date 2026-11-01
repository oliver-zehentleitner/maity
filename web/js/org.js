// The organigram, the Organisation tab of the Team page
// (/<owner>/<slug>/organisation; the maintainer, 2026-10-30; it was a
// section of the Overview): an indented tree computed from reports_to and
// area ownership on every render; nothing chart-shaped is stored or fetched.
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
        // A dormant instance answers only its own address (§6.17).
        M.dom.dormantOf(m).map((i) => h("span", { class: "muted member-dormant" }, M.dom.dormantNote(ctx, m, i)))),
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

  // The tab: the tree, drawn again from the members when one changes.
  M.views.organisation = async function (ctx, root) {
    const status = M.statusLine();
    const box = h("div", { class: "org-box" });
    append(root, M.teamTabs(ctx, "organisation"), h("h2", null, M.t("team.tab.organisation")),
      h("p", { class: "muted" }, M.t("org.intro", { preset: ctx.project.policy.preset })), status.el, box);
    append(box, drawTree(ctx));
    ctx.onEvents((events) => {
      if (!events.some((e) => /^member_/.test(e.kind))) return;
      M.api.getAll(ctx.base + "/members").then((r) => { M.withMembers(ctx, r.items); append(clear(box), drawTree(ctx)); status.done(); },
        (err) => status.fail(M.t("org.reread_failed"), err));
    });
  };

  M.org = { buildTree, drawTree, contains };
})(window.Maity);
