// (3) Agents and presence: profile, human owner, role, areas, live
// session, presence as the hub computes it, paused reason; credentials as
// id, dates and a revoke button, never their value. A human with
// members:admin pauses an agent that cannot say so itself.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, formatAgo, formatTime } = M.dom;

  const PRESENCE_LABELS = { online: "Online", away: "Away", offline: "Offline", paused: "Paused" };

  function credentials(ctx, m, list) {
    const box = h("div", { class: "credentials" }, h("h4", null, "Credentials"));
    if (!list.items.length) {
      append(box, h("p", { class: "muted" }, "None."));
      return box;
    }
    const status = M.statusLine();
    // Active ones first, as the hub lists them; revoked ones stay visible.
    append(box, h("ul", null, list.items.map((c) => h("li", { class: c.revoked_at ? "revoked" : "" },
      h("code", null, c.id),
      h("span", null, " " + (c.client || "") + " · created " + formatTime(c.created_at)),
      c.revoked_at
        ? h("span", { class: "muted" }, " · revoked " + formatTime(c.revoked_at) + " by " + ctx.nameOf(c.revoked_by)
          + (c.revoked_reason ? " (" + c.revoked_reason + ")" : ""))
        : [
          c.resumed_at
            ? h("span", null, " · last used " + formatAgo(c.last_used_at))
            : h("span", { class: "never" }, " · never resumed"),
          h("button", {
            type: "button",
            class: "danger",
            onclick: async (e) => {
              if (!window.confirm("Revoke " + c.id + " of " + m.display_name + "? Its session loses access at once.")) return;
              e.target.disabled = true;
              status.busy("Revoking…");
              try {
                await M.api.post(ctx.base + "/credentials/" + encodeURIComponent(c.id) + "/revoke", {});
                ctx.refresh();
              } catch (err) {
                e.target.disabled = false;
                status.fail("Not revoked: ", err);
              }
            },
          }, "Revoke"),
        ]))), status.el);
    return box;
  }

  function pauseControl(ctx, m) {
    const status = M.statusLine();
    const save = async (paused) => {
      status.busy("Saving…");
      try {
        await M.api.patch(ctx.base + "/members/" + encodeURIComponent(m.id), { paused });
        ctx.refresh();
      } catch (err) {
        status.fail("Not saved: ", err);
      }
    };
    if (m.paused) {
      return h("div", { class: "pause" },
        h("button", { type: "button", onclick: () => save(null) }, "Clear pause"), status.el);
    }
    const id = "pause-" + m.id;
    const reason = h("input", { id, placeholder: "Why it stopped" });
    return h("form", {
      class: "pause",
      onsubmit: (e) => {
        e.preventDefault();
        if (!reason.value.trim()) { reason.focus(); return; }
        save({ reason: reason.value.trim() });
      },
    },
    h("label", { for: id }, "Pause"), reason, h("button", { type: "submit" }, "Pause"), status.el);
  }

  M.views.agents = async function (ctx, root) {
    const agents = ctx.members.filter((m) => m.kind === "agent");
    const creds = await Promise.all(agents.map((m) =>
      M.api.getAll(ctx.base + "/members/" + encodeURIComponent(m.id) + "/credentials")));

    append(root, h("h2", null, "Agents"),
      h("div", { class: "profiles" }, agents.map((m, i) => {
        const mine = m.owner_id === ctx.me.id;
        const s = m.session;
        return h("article", { class: "profile", "aria-label": m.display_name },
          h("header", null,
            h("span", { class: "dot " + m.presence, "aria-hidden": "true" }),
            h("h3", null, m.display_name),
            h("span", { class: "handle" }, "@" + m.handle),
            h("span", { class: "presence " + m.presence }, PRESENCE_LABELS[m.presence] || m.presence)),
          h("dl", { class: "facts" },
            h("dt", null, "Owner"), h("dd", null, ctx.nameOf(m.owner_id)),
            h("dt", null, "Role"), h("dd", null, m.role),
            h("dt", null, "Reports to"), h("dd", null, ctx.nameOf(m.reports_to)),
            h("dt", null, "Areas"), h("dd", null, m.areas.length ? m.areas.join(", ") : "—"),
            m.capabilities && m.capabilities.length
              ? [h("dt", null, "Capabilities"), h("dd", null, m.capabilities.join(", "))]
              : null,
            h("dt", null, "Harness"), h("dd", null, (m.harness || "—") + (m.model ? " · " + m.model : "")),
            h("dt", null, "Session"), h("dd", null, s
              ? s.id + " since " + formatTime(s.started_at) + (s.client ? " · " + s.client : "")
                + (s.listening ? " · listening" : "")
              : "none"),
            h("dt", null, "Last seen"), h("dd", null, formatAgo(m.last_seen_at)),
            h("dt", null, "Joined"), h("dd", null, formatTime(m.joined_at))),
          m.paused
            ? h("p", { class: "flag" }, "Paused " + formatAgo(m.paused.since)
              + (m.paused.by && m.paused.by !== m.id ? " by " + ctx.nameOf(m.paused.by) : "") + ": " + m.paused.reason)
            : null,
          ctx.canAdmin ? pauseControl(ctx, m) : null,
          credentials(ctx, m, creds[i]),
          mine ? h("p", { class: "chat-link" }, h("a", { href: ctx.link("chat", m.id) }, "Chat")) : null);
      })));
  };
})(window.Maity);
