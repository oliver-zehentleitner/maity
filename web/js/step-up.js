// Sensitive calls (docs/api.md §2.8): the hub refuses one with
// `reauthentication_required` when the password was not given on this
// session in the last 10 minutes, and with `step_up_required` when an
// enrolled human has not given the second factor in the last 10 minutes.
// run() makes the call, and on either refusal asks for the password or a
// code in the slot it is given, proves it (POST /auth/reauthenticate,
// POST /auth/second-factor/verify) and makes the call again. Cancel ends
// with an ApiError of code "cancelled", which the caller says or ignores.
// A human without TOTP under the mail factor (§2.8.8) is sent a code by
// mail instead (POST /auth/second-factor/email) and types that.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  // A call that asked for a password and then for a code is made three times at most.
  const TRIES = 3;

  const ASK = {
    reauthentication_required: {
      get title() { return M.t("stepup.password.title"); },
      hint: (what) => M.t("stepup.password.hint", { what }),
      get label() { return M.t("stepup.password.label"); }, type: "password", autocomplete: "current-password",
      prove: (value) => M.api.post("/auth/reauthenticate", { password: value }),
      wrong: (err) => (err.code === "invalid" && err.details && err.details.fields && err.details.fields.password
        ? M.t("stepup.password.wrong") : err.code === "rate_limited" ? M.t("stepup.password.rate_limited") : null),
    },
    step_up_required: {
      get title() { return M.t("stepup.code.title"); },
      hint: (what) => M.t("stepup.code.hint", { what }),
      get label() { return M.t("stepup.code.label"); }, type: "text", autocomplete: "one-time-code",
      // A code may be typed with spaces ("482 913"): six digits without them are a code (§2.8.1).
      prove: (value) => {
        const digits = value.replace(/\s+/g, "");
        return M.api.post("/auth/second-factor/verify", /^\d{6}$/.test(digits) ? { code: digits } : { recovery_code: value });
      },
      wrong: (err) => (err.code === "code_invalid" ? M.t("stepup.code.wrong") : err.code === "rate_limited" ? M.t("stepup.code.rate_limited") : null),
    },
    // §2.8.8 rule 4: the code comes by mail, sent when the question opens, again on request.
    step_up_mail: {
      get title() { return M.t("stepup.mail.title"); },
      hint: (what) => M.t("stepup.mail.hint", { what }),
      get label() { return M.t("stepup.mail.label"); }, type: "text", autocomplete: "one-time-code",
      send: () => M.api.post("/auth/second-factor/email", {}),
      prove: (value) => M.api.post("/auth/second-factor/verify", { email_code: value.replace(/\s+/g, "") }),
      wrong: (err) => (err.code === "code_invalid" ? M.t("stepup.code.wrong") : err.code === "rate_limited" ? M.t("stepup.mail.rate_limited")
        : err.code === "mail_not_configured" ? M.t("sf.mail.not_configured") : err.code === "address_unverified" ? M.t("sf.mail.address_lost") : null),
    },
  };

  // Whether this human proves the factor by mail: GET /auth/second-factor says so in `via`
  // (§2.8.1, §2.8.8). A failed read keeps the code question.
  const byMail = () => M.api.get("/auth/second-factor").then((s) => !!s && s.via === "email", () => false);

  // Shows the question in slot; resolves once proven, rejects on Cancel. A
  // question still open in the slot (another call's) is cancelled first, so
  // that call does not wait for an answer that can no longer come.
  const open = new WeakMap();
  function ask(slot, reason, what) {
    const a = ASK[reason];
    if (open.has(slot)) open.get(slot)();
    return new Promise((resolve, reject) => {
      const id = "step-up-" + reason;
      const input = h("input", { id, type: a.type, autocomplete: a.autocomplete, "aria-describedby": id + "-error" });
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      const submit = h("button", { type: "submit" }, M.t("stepup.confirm"));
      const done = () => { open.delete(slot); clear(slot); slot.hidden = true; };
      // The mailed code: sent as the question opens; a failure is said where the code goes.
      const sent = a.send ? h("p", { class: "hint step-up-sent", role: "status" }) : null;
      async function send(again) {
        error.textContent = "";
        try {
          await a.send();
          sent.textContent = again ? M.t("stepup.mail.sent_again") : M.t("stepup.mail.sent");
        } catch (err) {
          sent.textContent = "";
          error.textContent = a.wrong(err) || M.t("stepup.not_confirmed", { reason: err.message });
        }
      }
      open.set(slot, () => { done(); reject(new M.api.ApiError(M.t("stepup.cancelled"), 0, "", "cancelled")); });
      const form = h("form", {
        class: "step-up inline-form",
        onsubmit: async (e) => {
          e.preventDefault();
          // A password is sent as typed; a code is trimmed.
          const value = a.type === "password" ? input.value : input.value.trim();
          if (!value) { input.focus(); return; }
          submit.disabled = true;
          error.textContent = "";
          try {
            await a.prove(value);
            done();
            resolve();
          } catch (err) {
            submit.disabled = false;
            error.textContent = a.wrong(err) || M.t("stepup.not_confirmed", { reason: err.message });
            input.value = "";
            input.focus();
          }
        },
      },
      h("h4", { class: "step-up-title" }, a.title),
      h("p", { class: "hint" }, a.hint(what || M.t("stepup.this_action"))), sent,
      h("label", { for: id }, a.label), input, submit,
      a.send ? h("button", { type: "button", class: "step-up-resend", onclick: () => send(true) }, M.t("stepup.mail.send_again")) : null,
      h("button", { type: "button", onclick: () => { done(); reject(new M.api.ApiError(M.t("stepup.cancelled"), 0, "", "cancelled")); } }, M.t("stepup.cancel")),
      error);
      if (a.send) send(false);
      slot.hidden = false;
      append(clear(slot), form);
      window.setTimeout(() => input.focus(), 0);
    });
  }

  // what: the action in words, as the question names it ("Exporting your data").
  async function run(call, slot, what) {
    for (let i = 1; ; i++) {
      try {
        return await call();
      } catch (err) {
        const reason = err && err.code === "forbidden" && err.details && err.details.reason;
        if (!ASK[reason] || i >= TRIES) throw err;
        await ask(slot, reason === "step_up_required" && await byMail() ? "step_up_mail" : reason, what);
      }
    }
  }

  M.stepUp = { run };
})(window.Maity);
