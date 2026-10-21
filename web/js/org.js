// (4) Organisation: an indented tree computed from reports_to and scope
// ownership on every render; nothing chart-shaped is stored or fetched.
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

  // The member owning the narrowest scope that contains one of m's scopes.
  function scopeParent(m, members) {
    let best = null;
    let bestLen = -1;
    members.forEach((other) => {
      if (other.id === m.id) return;
      other.scopes.forEach((outer) => {
        if (m.scopes.some((inner) => contains(outer, inner)) && outer.length > bestLen) {
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
        const p = scopeParent(m, members);
        if (p) parentOf[m.id] = { id: p.id, via: "scope" };
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

  function node(m, tree) {
    const kids = tree.children[m.id] || [];
    const link = tree.parentOf[m.id];
    const state = m.paused ? "paused" : (m.session ? "live" : "offline");
    return h("li", null,
      h("div", { class: "org-node" },
        h("span", { class: "dot " + (m.kind === "human" ? "human" : state), "aria-hidden": "true" }),
        h("strong", null, m.display_name),
        h("span", { class: "role" }, m.role),
        m.scopes.length ? h("span", { class: "scope" }, m.scopes.join(", ")) : null,
        link && link.via === "scope" ? h("span", { class: "muted" }, "(by scope)") : null),
      kids.length ? h("ul", null, kids.map((k) => node(k, tree))) : null);
  }

  M.views.org = async function (ctx, root) {
    const tree = buildTree(ctx.members);
    append(root, h("h2", null, "Organisation"),
      h("p", { class: "muted" }, "Model: " + (ctx.project.org_model || "—")
        + ". Computed from who reports to whom and who owns which scope."),
      h("ul", { class: "org-tree" }, tree.roots.map((m) => node(m, tree))));
  };

  M.org = { buildTree, contains };
})(window.Maity);
