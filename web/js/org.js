// The organigram, a section of Overview (js/overview.js; the maintainer,
// 2026-10-29): an indented tree computed from reports_to and area ownership
// on every render; nothing chart-shaped is stored or fetched.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

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
        link && link.via === "area" ? h("span", { class: "muted" }, "(by area)") : null),
      kids.length ? h("ul", null, kids.map((k) => node(ctx, k, tree))) : null);
  }

  function section(ctx) {
    const tree = buildTree(ctx.members || []);
    return h("section", { class: "overview-part overview-org", "aria-labelledby": "overview-org" },
      h("div", { class: "overview-head" }, h("h3", { id: "overview-org" }, "Organisation"),
        h("span", { class: "muted" }, "· Policy: " + ctx.project.policy.preset)),
      h("p", { class: "muted" }, "Computed from who reports to whom and who owns which area."),
      tree.roots.length ? h("ul", { class: "org-tree" }, tree.roots.map((m) => node(ctx, m, tree))) : h("p", { class: "muted" }, "No members."));
  }

  M.org = { buildTree, contains, section };
})(window.Maity);
