// Personal language, agents that stop listening, and browser notifications
// on the account (/account/notifications, docs/api.md §18.4): the account's wish, the browser's own permission beside
// it, the kinds, and whether a chat's or mention's text may be shown. The
// browser's permission is asked only when the human turns them on. The mail
// address where the instance sends mail; the modes and times follow.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  M.views = M.views || {};

  // Getters: the words are the catalog's when shown.
  const KINDS = ["inbox", "chat", "mention", "security"];
  // §18.4: the mode of a kind is its interval; chat and mention may carry the message text.
  const MAIL_MODES = ["immediate", "hourly", "daily", "weekly", "off"];
  const MAIL_MODE_LABELS = {
    get immediate() { return M.t("mail.mode.immediate"); },
    get hourly() { return M.t("mail.mode.hourly"); },
    get daily() { return M.t("mail.mode.daily"); },
    get weekly() { return M.t("mail.mode.weekly"); },
    get off() { return M.t("mail.mode.off"); },
  };
  const MAIL_KIND_LABELS = {
    get inbox() { return M.t("mail.kind.inbox"); },
    get chat() { return M.t("mail.kind.chat"); },
    get mention() { return M.t("mail.kind.mention"); },
    get security() { return M.t("mail.kind.security"); },
  };
  const WITH_CONTENT = ["chat", "mention"];
  const WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"];
  const WEEKDAY_LABELS = {
    get mon() { return M.t("mail.day.mon"); },
    get tue() { return M.t("mail.day.tue"); },
    get wed() { return M.t("mail.day.wed"); },
    get thu() { return M.t("mail.day.thu"); },
    get fri() { return M.t("mail.day.fri"); },
    get sat() { return M.t("mail.day.sat"); },
    get sun() { return M.t("mail.day.sun"); },
  };
  const HHMM = /^(?:[01]\d|2[0-3]):[0-5]\d$/;
  // The browser's own zone, proposed where the account still has the hub's default.
  const browserZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || null; } catch { return null; } };
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

  // The mail address (§18.4): set, sent again, removed. A new address waits in `pending_address`
  // until its link is followed; the confirmed one keeps receiving until then. Changing or removing
  // a confirmed address takes the password of a human who has one; without one the hub may hold
  // the change (202, `address_change`) for a session at least a day old, in the sessions list.
  // The hub checks the address; the form only refuses an empty one.
  function mailAddressForm(settings, saved) {
    const box = h("section", { class: "mail-address", "aria-labelledby": "mail-address-title" });
    const status = M.statusLine();
    const say = (words) => { status.done(); append(status.el, h("span", { class: "ok" }, words)); };
    function draw() {
      const email = settings.email;
      const confirmed = !!(email.address && email.verified_at);
      const input = h("input", { id: "mail-address", type: "email", autocomplete: "email", spellcheck: "false",
        "aria-describedby": "mail-address-error" });
      input.value = email.pending_address || email.address || "";
      const password = h("input", { id: "mail-address-password", type: "password", autocomplete: "current-password",
        "aria-describedby": "mail-address-password-hint mail-address-password-error" });
      const errors = {
        address: h("p", { class: "field-error", id: "mail-address-error", role: "alert" }),
        password: h("p", { class: "field-error", id: "mail-address-password-error", role: "alert" }),
      };
      const fail = (field, text) => {
        errors[field].textContent = text;
        (field === "address" ? input : password).setAttribute("aria-invalid", "true");
      };
      const buttons = [];
      // One PATCH of the address; the page follows the hub's answer, a held change included.
      async function send(address, busy) {
        Object.values(errors).forEach((x) => { x.textContent = ""; });
        input.removeAttribute("aria-invalid"); password.removeAttribute("aria-invalid");
        const body = { email: { address } };
        if (confirmed && password.value) body.current_password = password.value;
        buttons.forEach((b) => { b.disabled = true; });
        status.busy(busy);
        try {
          settings = await M.api.patch("/me/notification-settings", body);
          saved(settings);
          // Held is this change waiting (202), not an older one the hub still holds.
          const held = settings.email.address_change && settings.email.address_change.address === address;
          draw();
          if (held) say(M.t("mail.address.held"));
          else if (address === null) say(M.t("mail.address.removed"));
          else say(M.t("mail.address.sent", { address }));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields;
          if (fields && fields["email.address"]) fail("address", M.t("mail.address.invalid"));
          if (fields && fields.current_password === "required") fail("password", M.t("mail.address.password_required"));
          if (fields && fields.current_password === "mismatch") fail("password", M.t("mail.address.password_wrong"));
          // A session not in good standing may not replace a held change (§2.6.3): said with the
          // way to the sessions, which decide it. A session too young gets no refusal from a PATCH,
          // the hub holds its change instead, so that reason never comes here.
          if (err.code === "forbidden" && err.details && err.details.reason === "not_in_good_standing") {
            status.fail(M.t("notify.not_saved"), { message: "" });
            append(status.el, M.tn("mail.address.forbidden.not_in_good_standing", {
              link: h("a", { href: "/account/sessions" }, M.t("mail.address.held_link")) }));
          } else {
            status.fail(err.code === "mail_not_configured" ? M.t("mail.address.not_configured") : M.t("notify.not_saved"), err);
          }
          buttons.forEach((b) => { b.disabled = false; });
        }
      }
      const save = h("button", { type: "submit" }, M.t("mail.address.save"));
      const again = email.pending_address
        ? h("button", { type: "button", class: "secondary", onclick: () => send(email.pending_address, M.t("mail.address.sending")) }, M.t("mail.address.again"))
        : null;
      const remove = email.address || email.pending_address
        ? h("button", { type: "button", class: "secondary danger", onclick: () => {
          // Removing it stops all mail and a sign-in by mail: asked first.
          const ask = confirmed ? M.t("mail.address.remove_confirm", { address: email.address })
            : M.t("mail.address.remove_confirm_pending", { address: email.pending_address || email.address });
          if (!window.confirm(ask)) return;
          send(null, M.t("notify.saving"));
        } }, M.t("mail.address.remove"))
        : null;
      buttons.push(...[save, again, remove].filter(Boolean));
      const state = {
        none: () => M.t("mail.address.state.none"),
        pending: () => M.t("mail.address.state.pending", { pending: email.pending_address || "" }),
        verified: () => M.t("mail.address.state.verified", { address: email.address }),
        disabled: () => M.t("mail.address.state.disabled", { address: email.address }),
      }[email.address_status];
      const lines = [h("p", { class: "mail-address-state" }, state ? state() : email.address_status)];
      if (email.address_status !== "pending" && email.pending_address) {
        lines.push(h("p", { class: "hint" }, M.t("mail.address.waiting", { pending: email.pending_address, address: email.address })));
      }
      if (email.address_change) {
        lines.push(h("p", { class: "hint mail-address-held" }, M.tn("mail.address.held_hint", {
          link: h("a", { href: "/account/sessions" }, M.t("mail.address.held_link")) })));
      }
      append(clear(box),
        h("h3", { id: "mail-address-title" }, M.t("mail.address.title")),
        ...lines,
        h("form", {
          class: "mail-address-form",
          novalidate: true,
          onsubmit: (e) => {
            e.preventDefault();
            if (save.disabled) return;
            const address = input.value.trim();
            if (!address) { fail("address", M.t("mail.address.empty")); input.focus(); return; }
            send(address, M.t("mail.address.sending"));
          },
        },
        h("label", { for: "mail-address" }, M.t("mail.address.label")), input, errors.address,
        confirmed ? [
          h("label", { for: "mail-address-password" }, M.t("mail.address.password")), password,
          h("p", { class: "hint", id: "mail-address-password-hint" }, M.t("mail.address.password_hint")), errors.password,
        ] : null,
        h("div", { class: "actions" }, save, again, remove)),
        status.el);
    }
    draw();
    return box;
  }

  // When mail goes out (§18.4): a mode per kind, the text for chat and mention, the digests' time
  // and day in the account's zone, quiet hours and the sign-in link. The page reads the merged
  // values, so it sends only what was changed here: a kind sent back unchanged would count as
  // set and no longer follow a changed default.
  function mailModesForm(settings, saved) {
    const box = h("section", { class: "mail-modes", "aria-labelledby": "mail-modes-title" });
    const status = M.statusLine();
    function draw() {
      const email = settings.email;
      const kinds = KINDS.filter((k) => (settings.kinds || []).includes(k) && email.kinds && email.kinds[k]);
      const modes = {}, contents = {};
      const rows = kinds.map((k) => {
        const select = h("select", { id: "mail-mode-" + k, "aria-describedby": "mail-mode-" + k + "-error" },
          MAIL_MODES.map((v) => h("option", { value: v }, MAIL_MODE_LABELS[v])));
        select.value = email.kinds[k].mode;
        modes[k] = select;
        let content = null;
        if (WITH_CONTENT.includes(k)) {
          content = h("input", { type: "checkbox", id: "mail-content-" + k });
          content.checked = !!email.kinds[k].content;
          contents[k] = content;
        }
        return h("div", { class: "mail-kind" },
          h("label", { for: select.id }, MAIL_KIND_LABELS[k]), select,
          content ? h("label", { class: "check", for: content.id }, content, " " + M.t("mail.content")) : null,
          h("p", { class: "field-error", id: "mail-mode-" + k + "-error", role: "alert" }));
      });
      const dailyAt = h("input", { id: "mail-daily-at", type: "time", required: true, "aria-describedby": "mail-daily-at-error" });
      dailyAt.value = email.daily_at || "";
      const weeklyOn = h("select", { id: "mail-weekly-on" }, WEEKDAYS.map((d) => h("option", { value: d }, WEEKDAY_LABELS[d])));
      weeklyOn.value = email.weekly_on || "mon";
      const zone = h("input", { id: "mail-timezone", type: "text", autocomplete: "off", spellcheck: "false",
        "aria-describedby": "mail-timezone-hint mail-timezone-error" });
      zone.value = email.timezone || "";
      const own = browserZone();
      const useOwn = own && own !== email.timezone
        ? h("button", { type: "button", class: "small secondary", onclick: () => { zone.value = own; } }, M.t("mail.timezone.use", { zone: own }))
        : null;
      const quiet = h("input", { type: "checkbox", id: "mail-quiet" });
      quiet.checked = !!email.quiet_hours;
      const quietFrom = h("input", { id: "mail-quiet-from", type: "time", "aria-describedby": "mail-quiet-error" });
      const quietTo = h("input", { id: "mail-quiet-to", type: "time", "aria-describedby": "mail-quiet-error" });
      quietFrom.value = email.quiet_hours ? email.quiet_hours.from : "22:00";
      quietTo.value = email.quiet_hours ? email.quiet_hours.to : "07:00";
      const showQuiet = () => { quietFrom.disabled = !quiet.checked; quietTo.disabled = !quiet.checked; };
      quiet.addEventListener("change", showQuiet);
      showQuiet();
      const signIn = h("input", { type: "checkbox", id: "mail-sign-in-link" });
      signIn.checked = email.sign_in_link !== false;
      const errors = {
        daily_at: h("p", { class: "field-error", id: "mail-daily-at-error", role: "alert" }),
        timezone: h("p", { class: "field-error", id: "mail-timezone-error", role: "alert" }),
        quiet_hours: h("p", { class: "field-error", id: "mail-quiet-error", role: "alert" }),
      };
      const fieldOf = { daily_at: dailyAt, timezone: zone, quiet_hours: quietFrom };
      const fail = (field, text) => { errors[field].textContent = text; fieldOf[field].setAttribute("aria-invalid", "true"); };
      const button = h("button", { type: "submit" }, M.t("notify.save"));
      const form = h("form", {
        class: "mail-modes-form",
        novalidate: true,
        onsubmit: async (e) => {
          e.preventDefault();
          if (button.disabled) return;
          Object.values(errors).forEach((x) => { x.textContent = ""; });
          Object.values(fieldOf).forEach((x) => x.removeAttribute("aria-invalid"));
          box.querySelectorAll(".mail-kind .field-error").forEach((x) => { x.textContent = ""; });
          if (!HHMM.test(dailyAt.value)) { fail("daily_at", M.t("mail.time.invalid")); dailyAt.focus(); return; }
          if (!zone.value.trim()) { fail("timezone", M.t("mail.timezone.empty")); zone.focus(); return; }
          if (quiet.checked && !(HHMM.test(quietFrom.value) && HHMM.test(quietTo.value))) { fail("quiet_hours", M.t("mail.time.invalid")); quietFrom.focus(); return; }
          // Only what differs from the hub's answer; a kind only with the parts that changed.
          const patch = {};
          const changedKinds = {};
          kinds.forEach((k) => {
            const was = email.kinds[k], part = {};
            if (modes[k].value !== was.mode) part.mode = modes[k].value;
            if (contents[k] && contents[k].checked !== !!was.content) part.content = contents[k].checked;
            if (Object.keys(part).length) changedKinds[k] = part;
          });
          if (Object.keys(changedKinds).length) patch.kinds = changedKinds;
          if (dailyAt.value !== email.daily_at) patch.daily_at = dailyAt.value;
          if (weeklyOn.value !== email.weekly_on) patch.weekly_on = weeklyOn.value;
          if (zone.value.trim() !== email.timezone) patch.timezone = zone.value.trim();
          const hours = quiet.checked ? { from: quietFrom.value, to: quietTo.value } : null;
          if (JSON.stringify(hours) !== JSON.stringify(email.quiet_hours || null)) patch.quiet_hours = hours;
          if (signIn.checked !== (email.sign_in_link !== false)) patch.sign_in_link = signIn.checked;
          if (!Object.keys(patch).length) { status.done(); append(status.el, h("span", { class: "ok" }, M.t("notify.unchanged"))); return; }
          button.disabled = true;
          status.busy(M.t("notify.saving"));
          try {
            settings = await M.api.patch("/me/notification-settings", { email: patch });
            saved(settings);
            draw();
            status.done();
            append(status.el, h("span", { class: "ok" }, M.t("notify.saved")));
          } catch (err) {
            const fields = (err.code === "invalid" && err.details && err.details.fields) || {};
            Object.keys(fields).forEach((name) => {
              const kind = /^email\.kinds\.(\w+)/.exec(name);
              if (kind && byKind(kind[1])) byKind(kind[1]).textContent = M.t("mail.mode.unknown");
              if (name === "email.daily_at") fail("daily_at", M.t("mail.time.invalid"));
              if (name === "email.timezone") fail("timezone", M.t("mail.timezone.unknown"));
              if (name === "email.quiet_hours") fail("quiet_hours", M.t("mail.time.invalid"));
            });
            status.fail(M.t("notify.not_saved"), err);
            button.disabled = false;
          }
        },
      },
      h("fieldset", { class: "mail-kinds" }, h("legend", null, M.t("mail.kinds.legend")), rows),
      h("p", { class: "hint" }, M.t("mail.kinds.hint")),
      h("label", { for: "mail-daily-at" }, M.t("mail.daily_at")), dailyAt, errors.daily_at,
      h("label", { for: "mail-weekly-on" }, M.t("mail.weekly_on")), weeklyOn,
      h("label", { for: "mail-timezone" }, M.t("mail.timezone")), zone,
      h("p", { class: "hint", id: "mail-timezone-hint" }, M.t("mail.timezone.hint"), useOwn ? " " : null, useOwn), errors.timezone,
      h("fieldset", { class: "mail-quiet" }, h("legend", null, M.t("mail.quiet.legend")),
        h("label", { class: "check", for: "mail-quiet" }, quiet, " " + M.t("mail.quiet.on")),
        h("label", { for: "mail-quiet-from" }, M.t("mail.quiet.from")), quietFrom,
        h("label", { for: "mail-quiet-to" }, M.t("mail.quiet.to")), quietTo, errors.quiet_hours),
      h("label", { class: "check", for: "mail-sign-in-link" }, signIn, " " + M.t("mail.sign_in_link")),
      h("p", { class: "hint" }, M.t("mail.sign_in_link.hint")),
      button);
      const byKind = (k) => form.querySelector("#mail-mode-" + k + "-error");
      append(clear(box),
        h("h3", { id: "mail-modes-title" }, M.t("mail.modes.title")),
        email.address && email.verified_at ? null : h("p", { class: "hint mail-modes-unconfirmed" }, M.t("mail.modes.unconfirmed")),
        form, status.el);
    }
    draw();
    return box;
  }

  // The language of the dashboard and of the hub's own texts (§6.2), apart from the one agents
  // write in; no form while there is only one to have.
  function interfaceForm() {
    const session = M.api.session();
    const current = session && session.member && session.member.interface_language;
    const select = M.interfacePicker("interface-language", current || "", true);
    if (!select) return null;
    const status = M.statusLine();
    const button = h("button", { type: "submit" }, M.t("language.interface.save"));
    return h("form", { class: "inline-form interface-language", onsubmit: async (e) => {
      e.preventDefault();
      button.disabled = true;
      status.busy(M.t("notify.saving"));
      try {
        await M.api.patch("/me", { interface_language: select.value || null });
        M.redraw();  // reads the session again, and with it the language
      } catch (err) {
        button.disabled = false;
        status.fail(M.t("language.interface.failed"), err);
      }
    } }, h("h3", null, M.t("language.interface.title")), h("label", { for: "interface-language" }, M.t("language.interface.label")), select,
    h("p", { class: "hint" }, M.t("language.interface.hint")), button, status.el);
  }

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
      const picker = M.languagePicker("personal-language", settings.email.language);
      const language = picker.select;
      const own = interfaceForm();
      if (own) append(box, own);
      const languageStatus = M.statusLine();
      const button = h("button", { type: "submit" }, M.t("notify.language.save"));
      append(box, h("form", { class: "inline-form personal-language", onsubmit: async (e) => {
        e.preventDefault();
        if (button.disabled) return;
        button.disabled = true;
        languageStatus.busy(M.t("notify.saving"));
        try {
          settings = await M.api.patch("/me/notification-settings", { email: { language: language.value } });
          picker.set(settings.email.language);
          languageStatus.done();
          append(languageStatus.el, h("span", { class: "ok" }, M.t("notify.language.saved")));
        } catch (err) { languageStatus.fail(M.t("notify.language.failed"), err); }
        button.disabled = false;
      } }, h("h3", null, M.t("notify.language.title")), h("label", { for: "personal-language" }, M.t("notify.language.label")), picker.search, language,
      h("p", { class: "hint" }, M.t("notify.language.hint")),
      button, languageStatus.el));
    }
    // Mail only where the instance sends it (`mail_available`); the language above stays without it.
    if (settings.mail_available && settings.email) {
      append(box, mailAddressForm(settings, (now) => { settings = now; }));
      append(box, mailModesForm(settings, (now) => { settings = now; }));
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
      append(clear(body),
        h("label", { class: "check", for: "notify-browser" }, on, " " + M.t("notify.browser.label")),
        h("p", { class: "muted notify-permission" }, Object.hasOwn(PERMISSION, permission) ? PERMISSION[permission] : permission),
        h("fieldset", { class: "notify-kinds" }, h("legend", null, M.t("notify.kinds.legend")), kinds),
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

  // The hub's list (§6.2), read once a page; null if it can't be had, and then the next call tries again.
  let languages = null;
  const loadLanguages = () => {
    languages = languages || M.api.get("/languages")
      .then((answer) => (Array.isArray(answer.items) ? answer.items : null))
      .catch(() => null)
      .then((items) => { if (!items) languages = null; return items; });
    return languages;
  };

  M.languages = loadLanguages;

  // The languages the dashboard has, each by its own name; null while there is only one.
  // withBrowser adds the choice of no language of one's own, value "".
  M.interfacePicker = (id, current, withBrowser) => {
    if (M.i18n.available.length < 2) return null;
    const select = h("select", { id },
      withBrowser ? h("option", { value: "" }, M.t("language.interface.browser")) : null,
      // A value chosen where no catalog is here yet stays shown, or saving would clear it.
      [...M.i18n.available, ...(current && !M.i18n.available.includes(current) ? [current] : [])]
        .map((tag) => h("option", { value: tag }, M.languageName(tag))));
    select.value = current;
    return select;
  };

  // A language's own name from the browser, the tag if it has none: until the hub's list is here.
  M.languageName = (tag) => {
    try { return new Intl.DisplayNames([tag], { type: "language" }).of(tag) || tag; } catch { return tag; }
  };

  // Writes a language's own name, and again with the hub's when that differs: ICU has none for
  // some languages and answers in English, and the display should say what the picker says.
  M.writeLanguageName = (tag, write) => {
    const first = M.languageName(tag);
    write(first);
    loadLanguages().then((items) => {
      const listed = items && items.find((l) => l.tag === tag);
      if (listed && listed.name !== first) write(listed.name);
    });
  };

  // The languages the hub offers a person (`common`, §6.2), each by its own name, and one already
  // chosen outside them, with a field that narrows them:
  // by that name, the tag or the English name, so someone can find a script they can't type.
  M.languagePicker = (id, current) => {
    const select = h("select", { id });
    const search = h("input", { type: "search", class: "language-search", "aria-label": M.t("notify.language.search"), placeholder: M.t("notify.language.search") });
    let all = [{ tag: "en", name: "English" }, { tag: "de", name: "Deutsch" }];
    let chosen = current;
    const english = (tag) => { try { return new Intl.DisplayNames(["en"], { type: "language" }).of(tag) || ""; } catch { return ""; } };
    const fill = () => {
      const needle = search.value.trim().toLowerCase();
      const match = (l) => !needle || l.tag === chosen || [l.name, l.tag, english(l.tag)].some((text) => text.toLowerCase().includes(needle));
      const known = all.some((l) => l.tag === chosen) ? all : [...all, { tag: chosen, name: M.languageName(chosen) }];
      select.textContent = "";
      append(select, known.filter(match).map((l) => h("option", { value: l.tag }, l.name)));
      select.value = chosen;
    };
    select.addEventListener("change", () => { chosen = select.value; });
    search.addEventListener("input", fill);
    fill();
    loadLanguages().then((items) => { if (items) { all = items.filter((l) => l.common); fill(); } });  // else the two stay
    return { select, search, set: (tag) => { chosen = tag; fill(); } };
  };
})(window.Maity);
