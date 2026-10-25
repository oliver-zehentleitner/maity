// Instance administration: only capabilities already served by this hub.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const MAIL = "/admin/settings/mail";
  const fields = [
    ["host", "SMTP host", "text"], ["port", "SMTP port", "number"],
    ["tls", "Connection security", "select"], ["username", "SMTP username", "text"],
    ["from", "Sender", "sender"], ["reply_to", "Reply-to address", "email"],
    ["max_per_hour", "Notification mails per hour", "number"],
    ["security_max_per_hour", "Security mails per hour", "number"],
    ["sign_in_max_per_hour", "Sign-in mails per hour", "number"],
  ];
  const warnings = {
    smtp_password_in_database: "The SMTP password is stored in the database. On Kubernetes, configure it through a Secret.",
    smtp_plaintext_allowed: "The environment allows plaintext mail. Messages, including sign-in links, may cross the network unencrypted.",
    smtp_password_unreadable: "The stored SMTP password cannot be opened with the instance key. Set it again.",
  };
  async function served(method, path) {
    if (M.api.absent.has(method, path)) return false;
    try { return await M.api.hubHas(method, path); } catch (_) { return true; }
  }
  async function missing(err, method, path, section) {
    if (!await M.api.missingRoute(err, method, path)) return false;
    M.api.absent.note(method, path); section.remove(); return true;
  }
  function mailError(err) {
    const reasons = { set_by_environment: "set by the environment; reload to see its value", secret_key_missing: "the instance encryption key is not configured", loopback_host_only: "no TLS is allowed only for localhost", no_verified_address: "enter a recipient address", invalid: "invalid value", extra_forbidden: "not supported by this hub" };
    const errors = err.details && err.details.fields;
    if (!errors) return err;
    return { message: Object.entries(errors).map(([field, reason]) => field + ": " + (reasons[reason] || reason)).join("; ") };
  }
  function resultLine(value) {
    if (!value) return h("p", { class: "muted" }, "No test has been run with these settings.");
    return h("div", { class: "mail-test-result", role: "status" },
      h("p", { class: value.ok ? "ok" : "error" }, value.ok ? "Test mail sent." : "Test mail failed.",
        value.stage ? " Stage: " + value.stage + "." : "", value.smtp_code != null ? " SMTP code: " + value.smtp_code + "." : ""),
      value.detail ? h("p", { class: "message-body" }, value.detail) : null,
      value.at ? h("p", { class: "muted" }, formatTime(value.at)) : null);
  }
  async function mailSection(ctx, section) {
    const status = M.statusLine();
    append(section, h("h2", null, "Mail settings"), status.el);
    let current;
    try { current = await M.api.get(MAIL); }
    catch (err) { if (!await missing(err, "GET", MAIL, section)) status.fail("Mail settings could not be read: ", err); return; }
    const [canSave, canTest] = await Promise.all([served("PATCH", MAIL), served("POST", MAIL + "/test")]);
    const settings = h("div"), test = h("div", { class: "mail-test" });
    append(section, settings, test);
    function draw() {
      clear(settings);
      append(settings, h("p", { class: current.complete ? "muted" : "error" }, current.complete ? "Mail configuration is complete."
        : "Mail configuration is incomplete: " + (current.missing || []).join(", ") + "."),
      (current.warnings || []).map((w) => h("p", { class: "error" }, warnings[w] || w)),
      h("p", { class: "muted" }, "Signing key: " + (current.signing_key && current.signing_key.set ? "set" : "not set")
        + ". Instance encryption key: " + (current.secret_key && current.secret_key.set ? "set" : "not set") + ". Keys are configured in the environment."));
      const form = h("form", { class: "inline-form admin-mail-form" });
      const inputs = [];
      const enabled = h("input", { id: "mail-enabled", type: "checkbox", disabled: !canSave }); enabled.checked = !!current.enabled;
      append(form, h("label", { class: "check", for: enabled.id }, enabled, " Enable mail"));
      fields.forEach(([key, label, type]) => {
        const field = current[key]; if (!field) return;
        const locked = field.source === "env" || !canSave;
        const id = "mail-" + key;
        let input, name;
        if (type === "select") {
          input = h("select", { id, disabled: locked }, [["starttls", "STARTTLS (required)"], ["implicit", "TLS from connection start"], ["none", "No TLS (localhost only)"]]
            .map(([value, text]) => h("option", { value }, text)));
          input.value = field.value || "starttls";
        } else {
          input = h("input", { id, type: type === "sender" ? "email" : type, disabled: locked, autocomplete: "off" });
          input.value = type === "sender" ? (field.value || {}).address || "" : field.value == null ? "" : String(field.value);
        }
        append(form, h("label", { for: id }, label + (type === "sender" ? " address" : "")), input);
        if (type === "sender") {
          name = h("input", { id: id + "-name", disabled: locked, autocomplete: "off" }); name.value = (field.value || {}).name || "";
          append(form, h("label", { for: name.id }, "Sender name"), name);
        }
        append(form, h("p", { class: "hint" }, field.source === "env" ? "Set by the environment."
          : "Source: " + field.source + (type === "select" ? "." : ". Leave empty to restore the default.")));
        inputs.push({ key, type, input, name, locked, before: input.value, nameBefore: name && name.value });
      });
      const passwordLocked = !canSave || (current.password || {}).source === "env";
      const password = h("input", { id: "mail-password", type: "password", autocomplete: "new-password", disabled: passwordLocked });
      const remove = h("input", { id: "mail-password-remove", type: "checkbox", disabled: passwordLocked });
      append(form, h("label", { for: password.id }, "New SMTP password"), password,
        h("p", { class: "hint" }, "Password: " + ((current.password || {}).set ? "set" : "not set")
          + (passwordLocked && (current.password || {}).source === "env" ? " · set by the environment." : ". Leave empty to keep it. The saved password is never displayed.")),
        h("label", { class: "check", for: remove.id }, remove, " Delete stored SMTP password"));
      const save = h("button", { type: "submit" }, "Save mail settings");
      if (canSave) append(form, save);
      form.addEventListener("submit", async (e) => {
        e.preventDefault(); if (!canSave || save.disabled) return;
        const body = {};
        if (enabled.checked !== !!current.enabled) body.enabled = enabled.checked;
        for (const item of inputs) {
          const { key, type, input, name, locked, before, nameBefore } = item;
          if (locked || (input.value === before && (!name || name.value === nameBefore))) continue;
          const value = input.value.trim();
          if (type === "number" && value && !/^\d+$/.test(value)) { status.fail("Not saved: ", { message: "Use a whole number for " + key + "." }); input.focus(); return; }
          body[key] = !value ? null : type === "number" ? Number(value)
            : type === "sender" ? { address: value, name: name.value.trim() || null } : value;
        }
        if (!passwordLocked) {
          if (remove.checked && password.value) { status.fail("Not saved: ", { message: "Choose a new password or delete the stored one, not both." }); return; }
          if (remove.checked) body.password = null;
          else if (password.value) body.password = password.value;
        }
        if (!Object.keys(body).length) { status.done(); append(status.el, h("span", null, "No settings changed.")); return; }
        password.value = ""; save.disabled = true; status.busy("Saving…");
        try { current = await M.api.patch(MAIL, body); status.done(); draw(); append(status.el, h("span", { class: "ok" }, "Mail settings saved.")); }
        catch (err) { if (!await missing(err, "PATCH", MAIL, form)) status.fail("Mail settings not saved: ", mailError(err)); }
        finally { delete body.password; save.disabled = false; }
      });
      append(settings, form, h("p", { class: "muted" }, "Last hour: " + (current.sent_last_hour || 0) + " notification mails, "
        + (current.security_sent_last_hour || 0) + " security mails, " + (current.sign_in_sent_last_hour || 0) + " sign-in mails, "
        + (current.failed_last_hour || 0) + " failures; " + (current.security_queued || 0) + " security mails queued."));
      drawTest();
    }
    function drawTest() {
      clear(test); if (!canTest) return;
      const outcome = h("div", null, resultLine(current.last_test));
      const sending = M.statusLine();
      const to = h("input", { id: "mail-test-to", type: "email", required: true, autocomplete: "email" });
      const button = h("button", { type: "submit", disabled: !current.complete }, "Send test mail");
      append(test, h("h3", null, "Test send"), h("p", { class: "hint" }, "Sends one test mail using the saved settings, even when mail is disabled. Save any changes first."),
        h("form", { class: "inline-form admin-mail-test", onsubmit: async (e) => {
          e.preventDefault(); if (button.disabled || !to.value.trim()) return;
          button.disabled = true; sending.busy("Sending…");
          try { const result = await M.api.post(MAIL + "/test", { to: to.value.trim() }); current.last_test = result; append(clear(outcome), resultLine(result)); sending.done(); }
          catch (err) { if (!await missing(err, "POST", MAIL + "/test", test)) sending.fail("Test mail could not be sent: ", mailError(err)); }
          finally { button.disabled = !current.complete; }
        } }, h("label", { for: to.id }, "Recipient"), to, button, sending.el), outcome);
    }
    draw();
  }
  async function infoSection(section) {
    append(section, h("h2", null, "Instance information"));
    const status = M.statusLine(); append(section, status.el);
    try {
      const value = await M.api.get("/health"), db = value.database || {};
      append(section, h("dl", { class: "instance-info" }, h("dt", null, "Version"), h("dd", null, value.version || "Unknown"),
        h("dt", null, "Database"), h("dd", null, db.reachable ? "Reachable" : "Unreachable"),
        h("dt", null, "Migration revision"), h("dd", null, db.revision || "None"), h("dt", null, "Migration head"), h("dd", null, db.head || "Unknown")));
    } catch (err) {
      if (await missing(err, "GET", "/health", section)) return;
      if (err.code === "schema_outdated") append(section, h("p", { class: "error" }, "Database reachable, migration required."),
        h("p", null, "Revision: " + ((err.details || {}).revision || "None") + " · head: " + ((err.details || {}).head || "Unknown")));
      else status.fail("Instance health could not be read: ", err);
    }
  }
  M.views.instanceAdmin = async (ctx, root) => {
    append(root, h("h2", null, "Instance administration"));
    if (!ctx.me.instance_admin) { append(root, h("p", null, "Only the instance admin can open this area.")); return; }
    const parts = [["/admin/statistics", "Statistics", (s) => M.statistics.section(ctx, s)], ["/admin/users", "Users", (s) => M.views.adminUsers(ctx, s)], [MAIL, "Mail settings", (s) => mailSection(ctx, s)], ["/health", "Instance information", infoSection]];
    for (const [path, label, load] of parts) {
      if (!await served("GET", path)) continue;
      const section = h("section", { class: "panel admin-section", "aria-label": label }); append(root, section);
      try { await load(section); }
      catch (err) { if (!await missing(err, "GET", path, section)) { const status = M.statusLine(); status.fail(label + " could not be read: ", err); append(section, status.el); } }
    }
  };
})(window.Maity);
