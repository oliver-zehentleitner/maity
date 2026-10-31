// Instance administration.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const MAIL = "/admin/settings/mail";
  // Each field: its key, its label (read from the catalog when drawn), its kind.
  const fields = [
    ["host", () => M.t("mail.field.host"), "text"], ["port", () => M.t("mail.field.port"), "number"],
    ["tls", () => M.t("mail.field.tls"), "select"], ["username", () => M.t("mail.field.username"), "text"],
    ["from", () => M.t("mail.field.from_address"), "sender"], ["reply_to", () => M.t("mail.field.reply_to"), "email"],
    ["max_per_hour", () => M.t("mail.field.max_per_hour"), "number"],
    ["security_max_per_hour", () => M.t("mail.field.security_max_per_hour"), "number"],
    ["sign_in_max_per_hour", () => M.t("mail.field.sign_in_max_per_hour"), "number"],
  ];
  const warnings = {
    smtp_password_in_database: () => M.t("mail.warning.password_in_database"),
    smtp_plaintext_allowed: () => M.t("mail.warning.plaintext_allowed"),
    smtp_password_unreadable: () => M.t("mail.warning.password_unreadable"),
  };
  const REASONS = {
    set_by_environment: () => M.t("mail.reason.set_by_environment"), secret_key_missing: () => M.t("mail.reason.secret_key_missing"),
    loopback_host_only: () => M.t("mail.reason.loopback_host_only"), no_verified_address: () => M.t("mail.reason.no_verified_address"),
    invalid: () => M.t("mail.reason.invalid"), extra_forbidden: () => M.t("mail.reason.extra_forbidden"),
  };
  function mailError(err) {
    const errors = err.details && err.details.fields;
    if (!errors) return err;
    return { message: Object.entries(errors).map(([field, reason]) => field + ": " + (Object.hasOwn(REASONS, reason) ? REASONS[reason]() : reason)).join("; ") };
  }
  function resultLine(value) {
    if (!value) return h("p", { class: "muted" }, M.t("mail.test.none"));
    return h("div", { class: "mail-test-result", role: "status" },
      h("p", { class: value.ok ? "ok" : "error" }, value.ok ? M.t("mail.test.sent") : M.t("mail.test.failed"),
        value.stage ? [" ", M.t("mail.test.stage", { stage: value.stage })] : "",
        value.smtp_code != null ? [" ", M.t("mail.test.smtp_code", { code: String(value.smtp_code) })] : ""),
      value.detail ? h("p", { class: "message-body" }, value.detail) : null,
      value.at ? h("p", { class: "muted" }, formatTime(value.at)) : null);
  }
  async function mailSection(ctx, section) {
    const status = M.statusLine();
    append(section, h("h2", null, M.t("mail.title")), status.el);
    let current;
    try { current = await M.api.get(MAIL); }
    catch (err) { status.fail(M.t("mail.read_failed"), err); return; }
    const settings = h("div"), test = h("div", { class: "mail-test" });
    append(section, settings, test);
    function draw() {
      clear(settings);
      const setOrNot = (x) => (x && x.set ? M.t("mail.set") : M.t("mail.not_set"));
      append(settings, h("p", { class: current.complete ? "muted" : "error" }, current.complete ? M.t("mail.complete")
        : M.t("mail.incomplete", { missing: M.fmt.list(current.missing || []) })),
      (current.warnings || []).map((w) => h("p", { class: "error" }, Object.hasOwn(warnings, w) ? warnings[w]() : w)),
      h("p", { class: "muted" }, M.t("mail.keys", { signing: setOrNot(current.signing_key), secret: setOrNot(current.secret_key) })));
      const form = h("form", { class: "inline-form admin-mail-form" });
      const inputs = [];
      const enabled = h("input", { id: "mail-enabled", type: "checkbox", }); enabled.checked = !!current.enabled;
      append(form, h("label", { class: "check", for: enabled.id }, enabled, " ", M.t("mail.enable")));
      fields.forEach(([key, label, type]) => {
        const field = current[key]; if (!field) return;
        const locked = field.source === "env";
        const id = "mail-" + key;
        let input, name;
        if (type === "select") {
          input = h("select", { id, disabled: locked }, [["starttls", M.t("mail.tls.starttls")], ["implicit", M.t("mail.tls.implicit")], ["none", M.t("mail.tls.none")]]
            .map(([value, text]) => h("option", { value }, text)));
          input.value = field.value || "starttls";
        } else {
          input = h("input", { id, type: type === "sender" ? "email" : type, disabled: locked, autocomplete: "off" });
          input.value = type === "sender" ? (field.value || {}).address || "" : field.value == null ? "" : String(field.value);
        }
        append(form, h("label", { for: id }, label()), input);
        if (type === "sender") {
          name = h("input", { id: id + "-name", disabled: locked, autocomplete: "off" }); name.value = (field.value || {}).name || "";
          append(form, h("label", { for: name.id }, M.t("mail.field.from_name")), name);
        }
        append(form, h("p", { class: "hint" }, field.source === "env" ? M.t("mail.source.env")
          : type === "select" ? M.t("mail.source", { source: field.source }) : M.t("mail.source.default", { source: field.source })));
        inputs.push({ key, type, input, name, locked, before: input.value, nameBefore: name && name.value });
      });
      const passwordLocked = (current.password || {}).source === "env";
      const password = h("input", { id: "mail-password", type: "password", autocomplete: "new-password", disabled: passwordLocked });
      const remove = h("input", { id: "mail-password-remove", type: "checkbox", disabled: passwordLocked });
      append(form, h("label", { for: password.id }, M.t("mail.password.new")), password,
        h("p", { class: "hint" }, passwordLocked
          ? M.t("mail.password.env", { state: setOrNot(current.password) })
          : M.t("mail.password.hint", { state: setOrNot(current.password) })),
        h("label", { class: "check", for: remove.id }, remove, " ", M.t("mail.password.remove")));
      const save = h("button", { type: "submit" }, M.t("mail.save"));
      append(form, save);
      form.addEventListener("submit", async (e) => {
        e.preventDefault(); if (save.disabled) return;
        const body = {};
        if (enabled.checked !== !!current.enabled) body.enabled = enabled.checked;
        for (const item of inputs) {
          const { key, type, input, name, locked, before, nameBefore } = item;
          if (locked || (input.value === before && (!name || name.value === nameBefore))) continue;
          const value = input.value.trim();
          if (type === "number" && value && !/^\d+$/.test(value)) { status.fail(M.t("mail.not_saved"), { message: M.t("mail.whole_number", { key }) }); input.focus(); return; }
          body[key] = !value ? null : type === "number" ? Number(value)
            : type === "sender" ? { address: value, name: name.value.trim() || null } : value;
        }
        if (!passwordLocked) {
          if (remove.checked && password.value) { status.fail(M.t("mail.not_saved"), { message: M.t("mail.password.both") }); return; }
          if (remove.checked) body.password = null;
          else if (password.value) body.password = password.value;
        }
        if (!Object.keys(body).length) { status.done(); append(status.el, h("span", null, M.t("mail.unchanged"))); return; }
        password.value = ""; save.disabled = true; status.busy(M.t("mail.saving"));
        try { current = await M.api.patch(MAIL, body); status.done(); draw(); append(status.el, h("span", { class: "ok" }, M.t("mail.saved"))); }
        catch (err) { status.fail(M.t("mail.save_failed"), mailError(err)); }
        finally { delete body.password; save.disabled = false; }
      });
      append(settings, form, h("p", { class: "muted" }, M.t("mail.last_hour", {
        notifications: M.t("mail.count.notifications", { count: current.sent_last_hour || 0 }),
        security: M.t("mail.count.security", { count: current.security_sent_last_hour || 0 }),
        sign_in: M.t("mail.count.sign_in", { count: current.sign_in_sent_last_hour || 0 }),
        failures: M.t("mail.count.failures", { count: current.failed_last_hour || 0 }),
        queued: M.t("mail.count.queued", { count: current.security_queued || 0 }),
      })));
      drawTest();
    }
    function drawTest() {
      clear(test);
      const outcome = h("div", null, resultLine(current.last_test));
      const sending = M.statusLine();
      const to = h("input", { id: "mail-test-to", type: "email", required: true, autocomplete: "email" });
      const button = h("button", { type: "submit", disabled: !current.complete }, M.t("mail.test.send"));
      append(test, h("h3", null, M.t("mail.test.title")), h("p", { class: "hint" }, M.t("mail.test.hint")),
        h("form", { class: "inline-form admin-mail-test", onsubmit: async (e) => {
          e.preventDefault(); if (button.disabled || !to.value.trim()) return;
          button.disabled = true; sending.busy(M.t("mail.test.sending"));
          try { const result = await M.api.post(MAIL + "/test", { to: to.value.trim() }); current.last_test = result; append(clear(outcome), resultLine(result)); sending.done(); }
          catch (err) { sending.fail(M.t("mail.test.send_failed"), mailError(err)); }
          finally { button.disabled = !current.complete; }
        } }, h("label", { for: to.id }, M.t("mail.test.recipient")), to, button, sending.el), outcome);
    }
    draw();
  }
  async function infoSection(section) {
    append(section, h("h2", null, M.t("info.title")));
    const status = M.statusLine(); append(section, status.el);
    const unknown = () => M.t("info.unknown");
    try {
      const value = await M.api.get("/health"), db = value.database || {};
      append(section, h("dl", { class: "instance-info" }, h("dt", null, M.t("info.version")), h("dd", null, value.version || unknown()),
        h("dt", null, M.t("info.database")), h("dd", null, db.reachable ? M.t("info.reachable") : M.t("info.unreachable")),
        h("dt", null, M.t("info.revision")), h("dd", null, db.revision || M.t("info.none")), h("dt", null, M.t("info.head")), h("dd", null, db.head || unknown())));
    } catch (err) {
      if (err.code === "schema_outdated") append(section, h("p", { class: "error" }, M.t("info.migration_required")),
        h("p", null, M.t("info.revision_line", { revision: (err.details || {}).revision || M.t("info.none"), head: (err.details || {}).head || unknown() })));
      else status.fail(M.t("info.read_failed"), err);
    }
  }
  M.views.instanceAdmin = async (ctx, root, where) => {
    const into = (where && where.section) || null;
    append(root, h("h2", null, M.t("admin.title")));
    if (!ctx.me.instance_admin) { append(root, h("p", null, M.t("admin.only"))); return; }
    // Each section: the hub path it reads, the key of its id (the same in
    // every language), its label, and how it is drawn.
    const parts = [
      ["/admin/statistics", "statistics", M.t("admin.section.statistics"), (s) => M.statistics.section(ctx, s)],
      ["/admin/users", "users", M.t("admin.section.users"), (s) => M.adminUsers.section(ctx, s)],
      ["/admin/settings/limits", "limits", M.t("limits.section"), (s) => M.adminLimits.section(ctx, s)],
      ["/admin/reports", "reports", M.t("reports.section"), (s) => M.adminReports.section(ctx, s, into === "reports" ? where.args[0] || null : null)],
      [MAIL, "mail-settings", M.t("admin.section.mail"), (s) => mailSection(ctx, s)],
      ["/admin/settings/registration", "registration", M.t("admin.section.registration"), (s) => M.adminRegistration.section(ctx, s)],
      ["/admin/settings/landing", "landing-page", M.t("admin.section.landing"), (s) => M.landing.section(ctx, s)],
      ["/admin/settings/legal", "legal-pages", M.t("admin.section.legal"), (s) => M.legal.section(ctx, s)],
      ["/health", "instance-information", M.t("admin.section.info"), infoSection],
    ];
    // One section at a time, picked in a row of buttons at the top (the
    // designer's pass part 3: the page was one 5,000 px scroll); it opens
    // on the first, Statistics, or on the section the address names
    // (/admin/registration, /admin/reports[/<id>]: where a notification leads).
    const nav = h("nav", { class: "admin-nav", "aria-label": M.t("admin.sections") });
    append(root, nav);
    const shown = [];
    for (const [path, key, label, load] of parts) {
      const section = h("section", { class: "panel admin-section", "aria-label": label, id: "admin-" + key }); append(root, section);
      shown.push([label, section, path]);
      try { await load(section); }
      catch (err) { const status = M.statusLine(); status.fail(M.t("admin.section_failed", { section: label }), err); append(section, status.el); }
    }
    const buttons = shown.map(([label, section]) => h("button", { type: "button", "aria-controls": section.id, "aria-pressed": "false",
      onclick: () => pick(section) }, label));
    function pick(chosen) {
      shown.forEach(([, section], i) => {
        section.hidden = section !== chosen;
        buttons[i].setAttribute("aria-pressed", String(section === chosen));
      });
    }
    append(nav, buttons);
    // Matched by the hub path the section reads, not its label, which is translated.
    const named = into && shown.find(([, , path]) => path.endsWith("/" + into));
    if (shown.length) pick(named ? named[1] : shown[0][1]);
    else nav.remove();
  };
})(window.Maity);
