// Personal language, agents that stop listening, and browser notifications
// on the account (/account/notifications, docs/api.md §18.4): the account's wish, the browser's own permission beside
// it, the kinds, and whether a chat's or mention's text may be shown. The
// browser's permission is asked only when the human turns them on. Mail
// settings follow with the hub's mail (stage 3).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  M.views = M.views || {};

  const KINDS = [
    ["inbox", "Requests for you"],
    ["chat", "Chat messages"],
    ["mention", "Mentions of you"],
    ["security", "A new sign-in, a changed address"],
  ];
  const PERMISSION = {
    granted: "This browser shows them.",
    denied: "This browser blocks them: allow notifications for this site in the browser's settings.",
    default: "This browser has not been asked yet; it asks when you turn them on.",
  };

  const MODES = [
    ["inbox", "A request in my inbox, once an hour"],
    ["bell", "An item on the bell"],
    ["off", "Not at all"],
  ];
  // The hub's limits for the minutes (§18.4, §6.2), checked before sending.
  const MINUTES = { min: 10, max: 1440 };
  const minutesOk = (n) => Number.isInteger(n) && n >= MINUTES.min && n <= MINUTES.max;

  function notListeningForm(settings, saved) {
    const nl = settings.not_listening;
    const mode = h("select", { id: "not-listening-mode", "aria-describedby": "not-listening-mode-error" },
      MODES.map(([v, l]) => h("option", { value: v }, l)));
    mode.value = nl.mode;
    const minutes = h("input", { id: "not-listening-minutes", type: "number", min: String(MINUTES.min), max: String(MINUTES.max), step: "1",
      required: true, "aria-describedby": "not-listening-minutes-hint not-listening-minutes-error" });
    minutes.value = String(nl.minutes);
    const errors = {
      mode: h("p", { class: "field-error", id: "not-listening-mode-error", role: "alert" }),
      minutes: h("p", { class: "field-error", id: "not-listening-minutes-error", role: "alert" }),
    };
    const status = M.statusLine();
    const button = h("button", { type: "submit" }, "Save");
    const fail = (field, text) => { errors[field].textContent = text; (field === "mode" ? mode : minutes).setAttribute("aria-invalid", "true"); };
    return h("form", {
      class: "not-listening-settings",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        Object.values(errors).forEach((x) => { x.textContent = ""; });
        mode.removeAttribute("aria-invalid"); minutes.removeAttribute("aria-invalid");
        const n = Number(minutes.value);
        if (!minutesOk(n)) { fail("minutes", "A whole number of minutes from 10 to 1440."); minutes.focus(); return; }
        const patch = {};
        if (mode.value !== nl.mode) patch.mode = mode.value;
        if (n !== nl.minutes) patch.minutes = n;
        if (!Object.keys(patch).length) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
        button.disabled = true;
        status.busy("Saving…");
        try {
          const now = await M.api.patch("/me/notification-settings", { not_listening: patch });
          saved(now);
          Object.assign(nl, now.not_listening);
          mode.value = nl.mode; minutes.value = String(nl.minutes);
          status.done();
          append(status.el, h("span", { class: "ok" }, "Saved."));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          if (fields && fields["not_listening.minutes"]) fail("minutes", "A whole number of minutes from 10 to 1440.");
          if (fields && fields["not_listening.mode"]) fail("mode", "Not a choice of this hub.");
          status.fail("Not saved: ", err);
        }
        button.disabled = false;
      },
    },
    h("h3", null, "Agents that stop listening"),
    h("p", { class: "hint" }, "When one of your agent instances stops reading its events for a while, you hear of it here. "
      + "The member it reports to is told either way."),
    h("label", { for: "not-listening-mode" }, "Tell me"), mode, errors.mode,
    h("label", { for: "not-listening-minutes" }, "After how many minutes"), minutes,
    h("p", { class: "hint", id: "not-listening-minutes-hint" }, "10 to 1440. A project's My settings can set its own."),
    errors.minutes,
    button, status.el);
  }
  M.notListening = { MINUTES, minutesOk };

  M.notifySettings = async function (ctx) {
    const box = h("section", { class: "notify-settings", "aria-labelledby": "notify-heading" });
    const heading = h("h3", { id: "notify-heading", class: "notify-heading", tabindex: "-1" }, "Language and notifications");
    const status = M.statusLine();
    append(box, heading);
    let settings;
    try {
      settings = await M.api.get("/me/notification-settings");
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, "Could not read them: " + err.message));
      return { el: box, heading };
    }

    // Language belongs to the account, even without mail or browser notifications.
    if (settings.email && "language" in settings.email) {
      const language = h("select", { id: "personal-language" },
        h("option", { value: "en" }, "English"), h("option", { value: "de" }, "Deutsch"));
      language.value = settings.email.language;
      const languageStatus = M.statusLine();
      const button = h("button", { type: "submit" }, "Save personal language");
      append(box, h("form", { class: "inline-form personal-language", onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        button.disabled = true;
        languageStatus.busy("Saving…");
        try {
          settings = await M.api.patch("/me/notification-settings", { email: { language: language.value } });
          language.value = settings.email.language;
          languageStatus.done();
          append(languageStatus.el, h("span", { class: "ok" }, "Personal language saved."));
        } catch (err) { languageStatus.fail("Language not saved: ", err); }
        button.disabled = false;
      } }, h("h3", null, "Your language"), h("label", { for: "personal-language" }, "Language"), language,
      h("p", { class: "hint" }, "For messages addressed to you personally, and for emails and sign-in links."),
      button, languageStatus.el));
    }
    // Agent instances that stop listening (§5.3, §18.4): how one hears of
    // them and after how long; a project may override the minutes (My settings).
    append(box, notListeningForm(settings, (now) => { settings = now; }));
    if (!("Notification" in window)) {
      append(box, h("p", { class: "muted" }, "This browser cannot show notifications."));
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
      // Only the kinds the hub lists (its `kinds`).
      const known = (k) => (settings.kinds || []).includes(k);
      const kinds = KINDS.filter(([k]) => known(k)).map(([k, label]) => {
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

  // A project's Settings, the Mine tab (/<owner>/<slug>/settings/mine,
  // docs/api.md §6.2, §16.11): one's own settings for this project, each
  // either one's personal default (null) or a value for here, with the
  // value that applies now. Every human member; the Project tab beside it
  // is its admins'.
  M.mySettings = async function (ctx, root) {
    const heading = h("h3", { id: "my-settings-heading", tabindex: "-1" }, "Your settings for " + (ctx.project.name || ctx.slug));
    append(root, heading, h("p", { class: "hint" }, "Each one uses your default from ", h("a", { href: "/account/notifications" }, "Your account"), " unless you set it here."));
    if (ctx.me.kind !== "human") { append(root, h("p", null, "These are settings of a human member.")); return; }
    const path = ctx.base + "/me/settings";
    let mine;
    try {
      mine = await M.api.get(path);
    } catch (err) {
      append(root, h("p", { class: "send-status failed" }, "Could not read them: " + err.message));
      return;
    }
    const status = M.statusLine();
    const useDefault = h("input", { type: "radio", name: "my-nl", id: "my-nl-default", value: "default" });
    const useHere = h("input", { type: "radio", name: "my-nl", id: "my-nl-here", value: "here" });
    const minutes = h("input", { id: "my-nl-minutes", type: "number", min: String(M.notListening.MINUTES.min), max: String(M.notListening.MINUTES.max), step: "1",
      "aria-describedby": "my-nl-minutes-error" });
    const error = h("p", { class: "field-error", id: "my-nl-minutes-error", role: "alert" });
    const now = h("p", { class: "muted my-nl-effective" });
    const button = h("button", { type: "submit" }, "Save");
    function show(view) {
      const set = view.not_listening.minutes;
      useDefault.checked = set === null; useHere.checked = set !== null;
      minutes.value = String(set === null ? view.effective.not_listening.minutes : set);
      minutes.disabled = set === null;
      now.textContent = "Applies now: " + view.effective.not_listening.minutes + " minutes" + (set === null ? ", your default." : ", set here.");
    }
    [useDefault, useHere].forEach((r) => r.addEventListener("change", () => { minutes.disabled = !useHere.checked; if (useHere.checked) minutes.focus(); }));
    show(mine);
    append(root, h("form", {
      class: "project-form my-settings",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        error.textContent = ""; minutes.removeAttribute("aria-invalid");
        const value = useHere.checked ? Number(minutes.value) : null;
        if (value !== null && !M.notListening.minutesOk(value)) {
          error.textContent = "A whole number of minutes from 10 to 1440."; minutes.setAttribute("aria-invalid", "true"); minutes.focus(); return;
        }
        if (value === mine.not_listening.minutes) { status.done(); append(status.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
        button.disabled = true;
        status.busy("Saving…");
        try {
          mine = await M.api.patch(path, { not_listening: { minutes: value } });
          show(mine);
          status.done();
          append(status.el, h("span", { class: "ok" }, value === null ? "Saved: your default applies here." : "Saved for this project."));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          if (fields && fields["not_listening.minutes"]) { error.textContent = "A whole number of minutes from 10 to 1440."; minutes.setAttribute("aria-invalid", "true"); }
          status.fail("Not saved: ", err);
        }
        button.disabled = false;
      },
    },
    h("fieldset", { class: "my-nl" }, h("legend", null, "Agents that stop listening: after how many minutes"),
      h("label", { class: "check", for: "my-nl-default" }, useDefault, " Use my default"),
      h("label", { class: "check", for: "my-nl-here" }, useHere, " For this project:"),
      h("label", { class: "visually-hidden", for: "my-nl-minutes" }, "Minutes for this project"), minutes, error,
      h("p", { class: "hint" }, "How long one of your agent instances here may stop reading its events before you hear of it.")),
    now, button, status.el));
  };
})(window.Maity);
