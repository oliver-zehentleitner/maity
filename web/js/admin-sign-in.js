// Sign-in, a section of /admin (docs/api.md §2.6.6; js/instance-admin.js shows
// it to the instance admin only): the ways into this hub with each value's
// source (§16.2) and what the hub still lacks. One set by the environment is
// shown and not changed here. Only what changed is sent, and a change asks for
// the password or a code where the hub requires it (§2.8.4).
//
// "Mail for everyone" (§2.8.7, §2.8.8) is offered only while the mail settings
// are complete and enabled. Choosing it changes nothing yet: the hub answers 202
// and mails this admin a code, and the setting changes with that code, from this
// session. So the form stays open on a question until the code is typed.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const PATH = "/admin/settings/sign-in";
  const CONFIRM = PATH + "/second-factor-email/confirm";
  const SWITCHES = [
    { key: "device_code", label: () => M.t("admin_sign_in.device_code.label"), hint: () => M.t("admin_sign_in.device_code.hint") },
    { key: "email_link", label: () => M.t("admin_sign_in.email_link.label"), hint: () => M.t("admin_sign_in.email_link.hint") },
  ];
  const POLICIES = [
    ["off", () => M.t("admin_sign_in.policy.off")],
    ["optional", () => M.t("admin_sign_in.policy.optional")],
    ["required_admins", () => M.t("admin_sign_in.policy.required_admins")],
    ["email", () => M.t("admin_sign_in.policy.email")],
  ];
  const SOURCES = { default: () => M.t("limits.source.default"), admin: () => M.t("limits.source.admin") };
  const sourceWords = (v) => (v.source === "env" ? M.t("limits.locked")
    : M.t("limits.source", { source: Object.hasOwn(SOURCES, v.source) ? SOURCES[v.source]() : v.source }));
  const REASONS = {
    invalid: () => M.t("admin_sign_in.error.invalid"),
    set_by_environment: () => M.t("limits.error.env"),
    secret_key_missing: () => M.t("admin_sign_in.missing.secret_key"),
    mail_not_ready: () => M.t("admin_sign_in.error.mail_not_ready"),
    no_verified_address: () => M.t("admin_sign_in.error.no_verified_address"),
  };
  const reason = (why) => (Object.hasOwn(REASONS, why) ? REASONS[why]() : why);
  // Why the sign-in link by mail is not offered, and why TOTP is not.
  const MISSING = {
    switched_off: null, // the switch itself says so
    second_factor_email: () => M.t("admin_sign_in.missing.second_factor_email"),
    mail: () => M.t("admin_sign_in.missing.mail"),
    signing_key: () => M.t("admin_sign_in.missing.signing_key"),
    secret_key: () => M.t("admin_sign_in.missing.secret_key"),
  };

  async function section(ctx, root) {
    const status = M.statusLine();
    const body = h("div");
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    append(root, h("h2", null, M.t("admin_sign_in.title")), h("p", { class: "muted" }, M.t("admin_sign_in.intro")), status.el, stepSlot, body);
    let current = await M.api.get(PATH);

    // What the hub answered with 202: the code it mailed is the only way on.
    function askCode(expiresIn) {
      clear(body);
      const askStatus = M.statusLine();
      const error = h("p", { class: "field-error", id: "admin-sign-in-code-error", role: "alert" });
      const input = h("input", { id: "admin-sign-in-code", autocomplete: "one-time-code", spellcheck: "false",
        "aria-describedby": "admin-sign-in-code-hint admin-sign-in-code-error" });
      const confirm = h("button", { type: "submit", class: "primary" }, M.t("admin_sign_in.confirm.submit"));
      const words = (s) => M.t("admin_sign_in.confirm.lead", { count: Math.max(1, Math.round(s / 60)) });
      const lead = h("p", { id: "admin-sign-in-code-hint" }, words(expiresIn));
      const again = h("button", { type: "button", onclick: async () => {
        error.textContent = "";
        askStatus.busy(M.t("admin_sign_in.confirm.sending"));
        try {
          const sent = await M.stepUp.run(() => M.api.patch(PATH, { second_factor: "email" }), stepSlot, M.t("admin_sign_in.step_up"));
          lead.textContent = words(sent.expires_in);
          askStatus.done();
          input.focus();
        } catch (err) {
          if (err.code === "cancelled") { askStatus.done(); return; }
          const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.second_factor;
          if (why) { askStatus.done(); error.textContent = reason(why); return; }
          askStatus.fail(M.t("admin_sign_in.not_saved"), err);
        }
      } }, M.t("sf.mail.send_again"));
      // Leaving changes nothing: the setting was never changed, and the code runs out.
      const leave = h("button", { type: "button", class: "link-button", onclick: () => draw() }, M.t("admin_sign_in.confirm.leave"));
      append(body, h("form", {
        class: "inline-form admin-sign-in-confirm",
        onsubmit: async (e) => {
          e.preventDefault();
          error.textContent = "";
          input.removeAttribute("aria-invalid");
          const code = input.value.replace(/\s+/g, ""); // the mail writes it "123 456"
          if (!code) { error.textContent = M.t("admin_sign_in.confirm.empty"); input.setAttribute("aria-invalid", "true"); input.focus(); return; }
          confirm.disabled = true;
          askStatus.busy(M.t("admin_sign_in.confirm.checking"));
          try {
            current = await M.api.post(CONFIRM, { code });
            draw(M.t("admin_sign_in.confirm.done"));
          } catch (err) {
            confirm.disabled = false;
            if (err.code === "code_invalid") {
              askStatus.done();
              error.textContent = M.t("admin_sign_in.confirm.wrong");
              input.setAttribute("aria-invalid", "true");
              input.focus();
              return;
            }
            if (err.code === "rate_limited") {
              askStatus.done();
              const seconds = Number(err.details && err.details.retry_after) || 60;
              error.textContent = M.t("sf.rate_limited", { minutes: Math.max(1, Math.ceil(seconds / 60)) });
              return;
            }
            const why = err.code === "invalid" && err.details && err.details.fields && err.details.fields.second_factor;
            if (why) { askStatus.done(); error.textContent = reason(why); return; }
            askStatus.fail(M.t("admin_sign_in.not_saved"), err);
          }
        },
      }, lead, h("label", { for: "admin-sign-in-code" }, M.t("sf.email.label")), input, error, confirm, again, leave, askStatus.el));
      input.focus();
    }

    function draw(said) {
      clear(body);
      const formStatus = M.statusLine();
      const missing = current.missing || [];
      const notes = missing.filter((k) => Object.hasOwn(MISSING, k) && MISSING[k]).map((k) => MISSING[k]());
      const switches = SWITCHES.map((f) => {
        const v = current[f.key] || { value: true, source: "default" };
        const id = "admin-sign-in-" + f.key;
        const locked = v.source === "env";
        const box = h("input", { id, type: "checkbox", disabled: locked ? true : null, "aria-describedby": id + "-hint " + id + "-error" });
        box.checked = !!v.value;
        const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
        return { key: f.key, v, box, error, locked, nodes: h("div", { class: "field-stack" },
          h("label", { for: id }, box, " ", f.label()),
          h("p", { class: "hint", id: id + "-hint" }, f.hint() + " " + sourceWords(v)),
          error) };
      });
      const policy = current.second_factor || { value: "optional", source: "default" };
      const locked = policy.source === "env";
      // Mail for everyone only while the mail settings are complete and enabled and the key is
      // there (§2.8.7); a hub already on it keeps its word in the list, or the list would lie.
      const mailReady = !missing.includes("mail") && !missing.includes("signing_key");
      const select = h("select", { id: "admin-sign-in-second_factor", disabled: locked ? true : null,
        "aria-describedby": "admin-sign-in-second_factor-hint admin-sign-in-second_factor-note admin-sign-in-second_factor-error" },
        POLICIES.filter(([value]) => value !== "email" || mailReady || policy.value === "email")
          .map(([value, words]) => h("option", { value }, words())));
      select.value = policy.value;
      const note = h("p", { class: "hint", id: "admin-sign-in-second_factor-note" });
      const showNote = () => {
        note.textContent = select.value === "email" ? M.t("admin_sign_in.policy.email.note")
          : select.value === "required_admins" ? M.t("admin_sign_in.policy.required_admins.note") : "";
      };
      select.addEventListener("change", showNote);
      showNote();
      const policyError = h("p", { class: "field-error", id: "admin-sign-in-second_factor-error", role: "alert" });
      const save = h("button", { type: "submit" }, M.t("admin_sign_in.save"));
      append(body, h("form", {
        class: "inline-form admin-sign-in",
        onsubmit: async (e) => {
          e.preventDefault();
          const patch = {};
          switches.forEach((s) => {
            s.error.textContent = "";
            if (!s.locked && s.box.checked !== !!s.v.value) patch[s.key] = s.box.checked;
          });
          policyError.textContent = "";
          if (!locked && select.value !== policy.value) patch.second_factor = select.value;
          if (!Object.keys(patch).length) { formStatus.done(); append(formStatus.el, h("span", null, M.t("limits.unchanged"))); return; }
          save.disabled = true;
          formStatus.busy(M.t("limits.saving"));
          try {
            const answer = await M.stepUp.run(() => M.api.patch(PATH, patch), stepSlot, M.t("admin_sign_in.step_up"));
            if (patch.second_factor === "email") {
              // The rest of the form is saved; only this value waits for the code.
              askCode(answer.expires_in);
              M.api.get(PATH).then((v) => { current = v; }, () => {}); // the question stays open even if this read fails
              return;
            }
            current = answer;
            draw(M.t("limits.saved"));
          } catch (err) {
            save.disabled = false;
            if (err.code === "cancelled") { formStatus.done(); return; }
            const fields = err.code === "invalid" && err.details && err.details.fields;
            const atField = fields ? [...switches.map((s) => [s.key, s.error]), ["second_factor", policyError]].filter(([k]) => fields[k]) : [];
            if (atField.length) {
              formStatus.done();
              atField.forEach(([k, node]) => { node.textContent = reason(fields[k]); });
              return;
            }
            formStatus.fail(M.t("admin_sign_in.not_saved"), err);
          }
        },
      },
      h("p", { class: "hint" }, M.t("admin_sign_in.password")),
      switches.map((s) => s.nodes),
      h("div", { class: "field-stack" },
        h("label", { for: "admin-sign-in-second_factor" }, M.t("admin_sign_in.policy.label")), select,
        h("p", { class: "hint", id: "admin-sign-in-second_factor-hint" }, sourceWords(policy)),
        note, policyError),
      notes.length ? h("ul", { class: "hint admin-sign-in-missing" }, notes.map((n) => h("li", null, n))) : null,
      save, formStatus.el));
      if (said) append(body, h("p", { class: "ok", role: "status" }, said));
    }
    draw();
    status.done();
  }

  M.adminSignIn = { section };
})(window.Maity);
