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

  // Getters: the words are the catalog's when shown.
  const KINDS = ["inbox", "chat", "mention", "security"];
  const KIND_LABELS = {
    get inbox() { return M.t("notify.kind.inbox"); },
    get chat() { return M.t("notify.kind.chat"); },
    get mention() { return M.t("notify.kind.mention"); },
    get security() { return M.t("notify.kind.security"); },
  };
  const PERMISSION = {
    get granted() { return M.t("notify.permission.granted"); },
    get denied() { return M.t("notify.permission.denied"); },
    get default() { return M.t("notify.permission.default"); },
  };

  const MODES = ["inbox", "bell", "off"];
  const MODE_LABELS = {
    get inbox() { return M.t("notify.mode.inbox"); },
    get bell() { return M.t("notify.mode.bell"); },
    get off() { return M.t("notify.mode.off"); },
  };
  // The hub's limits for the minutes (§18.4, §6.2), checked before sending.
  const MINUTES = { min: 10, max: 1440 };
  const minutesOk = (n) => Number.isInteger(n) && n >= MINUTES.min && n <= MINUTES.max;
  // The limits as written, like a code: "10 to 1440".
  const range = () => M.t("notify.minutes.range", { min: String(MINUTES.min), max: String(MINUTES.max) });
  // A setting's own label and whether it is on now, said as one sentence.
  const toggled = (label, on) => (on ? M.t("notify.toggled.on", { label }) : M.t("notify.toggled.off", { label }));

  function notListeningForm(settings, saved) {
    const nl = settings.not_listening;
    const mode = h("select", { id: "not-listening-mode", "aria-describedby": "not-listening-mode-error" },
      MODES.map((v) => h("option", { value: v }, MODE_LABELS[v])));
    mode.value = nl.mode;
    const minutes = h("input", { id: "not-listening-minutes", type: "number", min: String(MINUTES.min), max: String(MINUTES.max), step: "1",
      required: true, "aria-describedby": "not-listening-minutes-hint not-listening-minutes-error" });
    minutes.value = String(nl.minutes);
    const errors = {
      mode: h("p", { class: "field-error", id: "not-listening-mode-error", role: "alert" }),
      minutes: h("p", { class: "field-error", id: "not-listening-minutes-error", role: "alert" }),
    };
    const status = M.statusLine();
    const button = h("button", { type: "submit" }, M.t("notify.save"));
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
        if (!minutesOk(n)) { fail("minutes", range()); minutes.focus(); return; }
        const patch = {};
        if (mode.value !== nl.mode) patch.mode = mode.value;
        if (n !== nl.minutes) patch.minutes = n;
        if (!Object.keys(patch).length) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("notify.unchanged"))); return; }
        button.disabled = true;
        status.busy(M.t("notify.saving"));
        try {
          const now = await M.api.patch("/me/notification-settings", { not_listening: patch });
          saved(now);
          Object.assign(nl, now.not_listening);
          mode.value = nl.mode; minutes.value = String(nl.minutes);
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("notify.saved")));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          if (fields && fields["not_listening.minutes"]) fail("minutes", range());
          if (fields && fields["not_listening.mode"]) fail("mode", M.t("notify.mode.unknown"));
          status.fail(M.t("notify.not_saved"), err);
        }
        button.disabled = false;
      },
    },
    h("h3", null, M.t("notify.nl.title")),
    h("p", { class: "hint" }, M.t("notify.nl.hint")),
    h("label", { for: "not-listening-mode" }, M.t("notify.nl.mode")), mode, errors.mode,
    h("label", { for: "not-listening-minutes" }, M.t("notify.nl.minutes")), minutes,
    h("p", { class: "hint", id: "not-listening-minutes-hint" }, M.t("notify.nl.minutes_hint", { min: String(MINUTES.min), max: String(MINUTES.max) })),
    errors.minutes,
    button, status.el);
  }
  M.notListening = { MINUTES, minutesOk };

  M.notifySettings = async function (ctx) {
    const box = h("section", { class: "notify-settings", "aria-labelledby": "notify-heading" });
    const heading = h("h3", { id: "notify-heading", class: "notify-heading", tabindex: "-1" }, M.t("notify.title"));
    const status = M.statusLine();
    append(box, heading);
    let settings;
    try {
      settings = await M.api.get("/me/notification-settings");
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, M.t("notify.read_failed", { reason: err.message })));
      return { el: box, heading };
    }

    // Language belongs to the account, even without mail or browser notifications.
    if (settings.email && "language" in settings.email) {
      // Each language by its own name, as its readers write it: no key.
      const language = h("select", { id: "personal-language" },
        h("option", { value: "en" }, "English"), h("option", { value: "de" }, "Deutsch"));
      language.value = settings.email.language;
      const languageStatus = M.statusLine();
      const button = h("button", { type: "submit" }, M.t("notify.language.save"));
      append(box, h("form", { class: "inline-form personal-language", onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        button.disabled = true;
        languageStatus.busy(M.t("notify.saving"));
        try {
          settings = await M.api.patch("/me/notification-settings", { email: { language: language.value } });
          language.value = settings.email.language;
          languageStatus.done();
          append(languageStatus.el, h("span", { class: "ok" }, M.t("notify.language.saved")));
        } catch (err) { languageStatus.fail(M.t("notify.language.failed"), err); }
        button.disabled = false;
      } }, h("h3", null, M.t("notify.language.title")), h("label", { for: "personal-language" }, M.t("notify.language.label")), language,
      h("p", { class: "hint" }, M.t("notify.language.hint")),
      button, languageStatus.el));
    }
    // Agent instances that stop listening (§5.3, §18.4): how one hears of
    // them and after how long; a project may override the minutes (My settings).
    append(box, notListeningForm(settings, (now) => { settings = now; }));
    if (!("Notification" in window)) {
      append(box, h("p", { class: "muted" }, M.t("notify.browser.unsupported")));
      return { el: box, heading };
    }

    // One change, as the hub merges it; the page follows the hub's answer.
    async function save(patch, words) {
      status.busy(M.t("notify.saving"));
      try {
        settings = await M.api.patch("/me/notification-settings", { browser: patch });
        M.notify.state.settings = settings;
        M.notify.startBrowser(ctx, settings);
        status.done();
        append(status.el, h("span", { class: "ok" }, words));
      } catch (err) {
        status.fail(M.t("notify.not_saved"), err);
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
        save({ enabled: on.checked }, on.checked ? M.t("notify.browser.on") : M.t("notify.browser.off"));
      });
      // Only the kinds the hub lists (its `kinds`).
      const known = (k) => (settings.kinds || []).includes(k);
      const kinds = KINDS.filter((k) => known(k)).map((k) => {
        const label = KIND_LABELS[k];
        const box2 = h("input", { type: "checkbox", id: "notify-kind-" + k, disabled: b.enabled ? null : true });
        box2.checked = !!b.kinds[k];
        box2.addEventListener("change", () => save({ kinds: { [k]: box2.checked } }, toggled(label, box2.checked)));
        return h("label", { class: "check", for: box2.id }, box2, " " + label);
      });
      const texts = [["chat", M.t("notify.content.chat")], ["mention", M.t("notify.content.mention")]].map(([k, label]) => {
        const box3 = h("input", { type: "checkbox", id: "notify-content-" + k, disabled: b.enabled ? null : true });
        box3.checked = !!(b.content && b.content[k]);
        box3.addEventListener("change", () => save({ content: { [k]: box3.checked } }, toggled(label, box3.checked)));
        return h("label", { class: "check", for: box3.id }, box3, " " + label);
      });
      append(clear(body),
        h("label", { class: "check", for: "notify-browser" }, on, " " + M.t("notify.browser.label")),
        h("p", { class: "muted notify-permission" }, Object.hasOwn(PERMISSION, permission) ? PERMISSION[permission] : permission),
        h("fieldset", { class: "notify-kinds" }, h("legend", null, M.t("notify.kinds.legend")), kinds),
        h("fieldset", { class: "notify-kinds" }, h("legend", null, M.t("notify.content.legend")), texts,
          h("p", { class: "hint" }, M.t("notify.content.hint"))),
        h("p", { class: "hint" }, M.t("notify.browser.hint")));
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
    const heading = h("h3", { id: "my-settings-heading", tabindex: "-1" }, M.t("mine.title", { name: ctx.project.name || ctx.slug }));
    append(root, heading, h("p", { class: "hint" }, M.tn("mine.hint", { link: h("a", { href: "/account/notifications" }, M.t("mine.account")) })));
    if (ctx.me.kind !== "human") { append(root, h("p", null, M.t("mine.humans_only"))); return; }
    const path = ctx.base + "/me/settings";
    let mine;
    try {
      mine = await M.api.get(path);
    } catch (err) {
      append(root, h("p", { class: "send-status failed" }, M.t("notify.read_failed", { reason: err.message })));
      return;
    }
    const status = M.statusLine();
    const useDefault = h("input", { type: "radio", name: "my-nl", id: "my-nl-default", value: "default" });
    const useHere = h("input", { type: "radio", name: "my-nl", id: "my-nl-here", value: "here" });
    const minutes = h("input", { id: "my-nl-minutes", type: "number", min: String(M.notListening.MINUTES.min), max: String(M.notListening.MINUTES.max), step: "1",
      "aria-describedby": "my-nl-minutes-error" });
    const error = h("p", { class: "field-error", id: "my-nl-minutes-error", role: "alert" });
    const now = h("p", { class: "muted my-nl-effective" });
    const button = h("button", { type: "submit" }, M.t("notify.save"));
    function show(view) {
      const set = view.not_listening.minutes;
      useDefault.checked = set === null; useHere.checked = set !== null;
      minutes.value = String(set === null ? view.effective.not_listening.minutes : set);
      minutes.disabled = set === null;
      const count = view.effective.not_listening.minutes;
      now.textContent = set === null ? M.t("mine.applies_default", { count }) : M.t("mine.applies_here", { count });
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
          error.textContent = range(); minutes.setAttribute("aria-invalid", "true"); minutes.focus(); return;
        }
        if (value === mine.not_listening.minutes) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("notify.unchanged"))); return; }
        button.disabled = true;
        status.busy(M.t("notify.saving"));
        try {
          mine = await M.api.patch(path, { not_listening: { minutes: value } });
          show(mine);
          status.done();
          append(status.el, h("span", { class: "ok" }, value === null ? M.t("mine.saved_default") : M.t("mine.saved_here")));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          if (fields && fields["not_listening.minutes"]) { error.textContent = range(); minutes.setAttribute("aria-invalid", "true"); }
          status.fail(M.t("notify.not_saved"), err);
        }
        button.disabled = false;
      },
    },
    h("fieldset", { class: "my-nl" }, h("legend", null, M.t("mine.legend")),
      h("label", { class: "check", for: "my-nl-default" }, useDefault, " " + M.t("mine.use_default")),
      h("label", { class: "check", for: "my-nl-here" }, useHere, " " + M.t("mine.here")),
      h("label", { class: "visually-hidden", for: "my-nl-minutes" }, M.t("mine.minutes_label")), minutes, error,
      h("p", { class: "hint" }, M.t("mine.hint_minutes"))),
    now, button, status.el));
  };
})(window.Maity);
