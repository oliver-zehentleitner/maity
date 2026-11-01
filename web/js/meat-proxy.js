// The meat-proxy switch of one chat (docs/api.md §9.3 "Meat proxy per chat",
// tsk-n872zkxmwbec): beside Attach and Send, for a human participant only. It
// shows the value that holds in this chat; a click switches it for this chat
// (`true`/`false`), and "Follow my profile" gives the choice back (`null`).
// The hub emits no event for it, so the switch draws from its own answer.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;

  // own: the caller's entry in the chat's participants, or null; base: the
  // conversation's path. Nothing for an agent, an observer (no entry of its
  // own) or a hub whose entry has no meat_proxy field.
  function toggle(ctx, base, own) {
    if (ctx.me.kind !== "human" || !own || !("meat_proxy" in own)) return null;
    let chosen = own.meat_proxy_chat === true || own.meat_proxy_chat === false ? own.meat_proxy_chat : null;
    let holds = !!own.meat_proxy;
    const status = M.statusLine();
    const button = h("button", { type: "button", class: "icon-button meat-chat-toggle", "aria-label": M.t("meat.chat.label") },
      h("span", { class: "meat-chat-icon", "aria-hidden": "true" }));
    const follow = h("button", { type: "button", class: "link-button meat-chat-follow" }, M.t("meat.chat.follow"));
    function draw() {
      button.setAttribute("aria-pressed", String(holds));
      button.setAttribute("title", chosen === null
        ? (holds ? M.t("meat.chat.state.on_profile") : M.t("meat.chat.state.off_profile"))
        : (holds ? M.t("meat.chat.state.on_chat") : M.t("meat.chat.state.off_chat")));
      follow.hidden = chosen === null;
    }
    async function set(value) {
      try { await M.api.put(base + "/meat-proxy", { meat_proxy: value }); } catch (err) { status.fail(M.t("meat.chat.not_saved"), err); return; }
      chosen = value;
      // null follows the profile (§5.2); the hub said nothing else, so the profile's value is the one held.
      holds = value === null ? !!ctx.me.meat_proxy : value;
      status.done();
      draw();
    }
    button.addEventListener("click", () => set(!holds));
    follow.addEventListener("click", () => set(null));
    draw();
    return h("div", { class: "meat-chat" }, button, follow, status.el);
  }

  M.meatProxy = { toggle };
})(window.Maity);
