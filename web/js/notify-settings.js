// Browser notifications on the account (#/account/notifications, docs/api.md
// §17.4 browser): the account's wish, the browser's own permission beside
// it, the kinds, and whether a chat's or mention's text may be shown. The
// browser's permission is asked only when the human turns them on. Mail
// settings follow with the hub's mail (stage 3).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const KINDS = [
    ["inbox", "Requests for you"],
    ["chat", "Chat messages"],
    ["mention", "Mentions of you"],
    ["card", "Changes on your cards"],
    ["agent", "An agent of yours stopped"],
    ["jour_fixe", "Jour fixe (none yet)"],
  ];
  const PERMISSION = {
    granted: "This browser shows them.",
    denied: "This browser blocks them: allow notifications for this site in the browser's settings.",
    default: "This browser has not been asked yet; it asks when you turn them on.",
  };

  M.notifySettings = async function (ctx) {
    const box = h("section", { class: "notify-settings", "aria-labelledby": "notify-heading" });
    const heading = h("h3", { id: "notify-heading", class: "notify-heading", tabindex: "-1" }, "Browser notifications");
    const status = M.statusLine();
    append(box, heading);
    if (!("Notification" in window)) {
      append(box, h("p", { class: "muted" }, "This browser cannot show notifications."));
      return { el: box, heading };
    }
    let settings;
    try {
      settings = await M.api.get("/me/notification-settings");
    } catch (err) {
      append(box, h("p", { class: "muted" }, err.status === 404 ? "This hub has no notification settings yet." : "Could not read them: " + err.message));
      return { el: box, heading };
    }

    // One change, as the hub merges it; the page follows the hub's answer.
    async function save(patch, words) {
      status.busy("Saving…");
      try {
        settings = await M.api.patch("/me/notification-settings", { browser: patch });
        M.notify.state.settings = settings;
        M.notify.startBrowser(ctx, settings);
        status.done();
        append(status.el, h("span", { class: "ok" }, words));
      } catch (err) {
        status.fail("Not saved: ", err);
      }
      draw();
    }

    const body = h("div");
    function draw() {
      const b = settings.browser;
      const permission = window.Notification.permission;
      const on = h("input", { type: "checkbox", id: "notify-browser" });
      on.checked = !!b.enabled;
      on.addEventListener("change", async () => {
        if (on.checked && window.Notification.permission === "default") {
          // Asked here, on the human's click, and nowhere else.
          try { await window.Notification.requestPermission(); } catch (ignored) { /* the state below says what the browser decided */ }
        }
        save({ enabled: on.checked }, on.checked ? "Browser notifications are on." : "Browser notifications are off.");
      });
      const kinds = KINDS.map(([k, label]) => {
        const box2 = h("input", { type: "checkbox", id: "notify-kind-" + k, disabled: b.enabled ? null : true });
        box2.checked = !!b.kinds[k];
        box2.addEventListener("change", () => save({ kinds: { [k]: box2.checked } }, label + (box2.checked ? ": on." : ": off.")));
        return h("label", { class: "check", for: box2.id }, box2, " " + label);
      });
      const texts = [["chat", "Show a chat message's first words"], ["mention", "Show a mention's first words"]].map(([k, label]) => {
        const box3 = h("input", { type: "checkbox", id: "notify-content-" + k, disabled: b.enabled ? null : true });
        box3.checked = !!(b.content && b.content[k]);
        box3.addEventListener("change", () => save({ content: { [k]: box3.checked } }, label + (box3.checked ? ": on." : ": off.")));
        return h("label", { class: "check", for: box3.id }, box3, " " + label);
      });
      append(clear(body),
        h("label", { class: "check", for: "notify-browser" }, on, " Show notifications while a Maity tab is open, also in the background"),
        h("p", { class: "muted notify-permission" }, PERMISSION[permission] || permission),
        h("fieldset", { class: "notify-kinds" }, h("legend", null, "For"), kinds),
        h("fieldset", { class: "notify-kinds" }, h("legend", null, "Text in the notification"), texts,
          h("p", { class: "hint" }, "Without it a notification says who and where only. The system may show the text on a locked screen.")),
        h("p", { class: "hint" }, "Nothing is shown for what you do yourself, and nothing arrives while no Maity tab is open."));
    }
    draw();
    append(box, body, status.el);
    return { el: box, heading };
  };
})(window.Maity);
