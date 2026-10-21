// (3) Agents and presence: profile, human owner, role, live session, last
// seen, paused reason; credentials as id, dates and a revoke button, never
// their value.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, formatAgo, formatTime } = M.dom;

  function presence(m) {
    if (m.paused) return { cls: "paused", label: "Paused" };
    if (m.session) return { cls: "live", label: "Live" };
    return { cls: "offline", label: "Offline" };
  }

  function credentials(ctx, m, list) {
    const box = h("div", { class: "credentials" }, h("h4", null, "Credentials"));
    if (!list.items.length) {
      box.append(h("p", { class: "muted" }, "None."));
      return box;
    }
    const status = h("p", { class: "send-status", role: "status" });
    box.append(h("ul", null, list.items.map((c) => h("li", null,
      h("code", null, c.id),
      h("span", null, " created " + formatTime(c.created_at) + " · last used " + formatAgo(c.last_used_at)),
      h("button", {
        type: "button",
        class: "danger",
        onclick: async (e) => {
          if (!window.confirm("Revoke " + c.id + " of " + m.display_name + "? Its session loses access at once.")) return;
          e.target.disabled = true;
          try {
            await M.api.post(ctx.base + "/credentials/" + encodeURIComponent(c.id) + "/revoke");
            ctx.refresh();
          } catch (err) {
            e.target.disabled = false;
            status.textContent = "Not revoked: " + err.message;
            status.className = "send-status failed";
          }
        },
      }, "Revoke")))), status);
    return box;
  }

  M.views.agents = async function (ctx, root) {
    const agents = ctx.members.filter((m) => m.kind === "agent");
    const creds = await Promise.all(agents.map((m) =>
      M.api.get(ctx.base + "/members/" + encodeURIComponent(m.id) + "/credentials")));

    root.append(h("h2", null, "Agents"),
      h("div", { class: "profiles" }, agents.map((m, i) => {
        const p = presence(m);
        const mine = m.owner_id === ctx.me.id;
        return h("article", { class: "profile", "aria-label": m.display_name },
          h("header", null,
            h("span", { class: "dot " + p.cls, "aria-hidden": "true" }),
            h("h3", null, m.display_name),
            h("span", { class: "handle" }, "@" + m.handle),
            h("span", { class: "presence " + p.cls }, p.label)),
          h("dl", { class: "facts" },
            h("dt", null, "Owner"), h("dd", null, ctx.nameOf(m.owner_id)),
            h("dt", null, "Role"), h("dd", null, m.role),
            h("dt", null, "Reports to"), h("dd", null, ctx.nameOf(m.reports_to)),
            h("dt", null, "Scopes"), h("dd", null, m.scopes.length ? m.scopes.join(", ") : "—"),
            h("dt", null, "Harness"), h("dd", null, (m.harness || "—") + (m.model ? " · " + m.model : "")),
            h("dt", null, "Session"), h("dd", null, m.session
              ? m.session.id + " since " + formatTime(m.session.started_at)
              : "none"),
            h("dt", null, "Last seen"), h("dd", null, formatAgo(m.last_seen_at))),
          m.paused
            ? h("p", { class: "flag" }, "Paused " + formatAgo(m.paused.since) + ": " + m.paused.reason)
            : null,
          credentials(ctx, m, creds[i]),
          mine ? h("p", { class: "chat-link" }, h("a", { href: "#/chat/" + encodeURIComponent(m.id) }, "Chat")) : null);
      })));
  };
})(window.Maity);
