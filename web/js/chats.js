// Every chat across one's projects (#/chats), where the header's Chat
// button leads. The hub lists conversations per project (docs/api.md
// §9.3), so each project is read on its own; unread chats first, then the
// newest. A chat opens in its project's Chat tab.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo } = M.dom;

  // The counterpart of a direct chat is the agent; a group chat is its
  // title, or the others' handles where it has none (§9.3).
  function titleOf(c, meId) {
    if (c.kind === "direct") {
      const agent = (c.participants || []).find((p) => p.kind === "agent");
      return agent ? "@" + agent.handle : "@" + c.agent_id;
    }
    return c.title || (c.participants || []).filter((p) => p.member_id !== meId).map((p) => "@" + p.handle).join(", ") || "Group chat";
  }

  const unreadOf = (c) => c.unread || 0;

  // Unread first, then the newest; without a message last.
  function ordered(chats) {
    const at = (c) => c.last_message_at || c.created_at || "";
    return chats.slice().sort((a, b) => (unreadOf(b) ? 1 : 0) - (unreadOf(a) ? 1 : 0) || (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : 0));
  }

  // Every project's list, each project's failure kept apart from the rest.
  async function read(ctx) {
    const lists = await Promise.all(ctx.projects.map((p) => M.api.getAll("/projects/" + encodeURIComponent(p.slug) + "/conversations")
      .then((r) => ({ project: p, items: r.items }), (err) => ({ project: p, items: [], err }))));
    const chats = [];
    lists.forEach((l) => l.items.forEach((c) => chats.push(Object.assign({}, c, { project: l.project }))));
    return { chats: ordered(chats), failed: lists.filter((l) => l.err) };
  }

  M.views.chats = async function (ctx, root) {
    append(root, h("h2", null, "Chats"),
      h("p", { class: "muted" }, "Your chats in every project, unread first."));
    const { chats, failed } = await read(ctx);
    const apart = (t) => h("span", { class: "visually-hidden" }, t);
    append(root,
      failed.map((l) => h("p", { class: "send-status failed" }, "Could not read the chats of " + l.project.name + ": " + l.err.message)),
      chats.length
        ? h("ul", { class: "chats-all" }, chats.map((c) => {
          const n = unreadOf(c);
          return h("li", null, h("a", {
            class: "conv" + (n ? " unread" : ""),
            href: "#/p/" + encodeURIComponent(c.project.slug) + "/chat/" + encodeURIComponent(c.id),
          },
          h("span", { class: "conv-title" }, titleOf(c, ctx.me.id)),
          apart(", "), h("span", { class: "muted chats-project" }, c.project.name),
          c.last_message_at ? [apart(", "), h("span", { class: "conv-time" }, formatAgo(c.last_message_at))] : null,
          n ? [apart(", "), h("span", { class: "count" }, String(n)), apart(" unread")] : null));
        }))
        : h("p", { class: "muted" }, failed.length ? "" : "No chats yet. A chat starts in a project's Chat tab."));
  };

  M.chats = { read, titleOf };
})(window.Maity);
