// Sensitive calls (docs/api.md §2.8): the hub refuses one with
// `reauthentication_required` when the password was not given on this
// session in the last 10 minutes, and with `step_up_required` when an
// enrolled human has not given the second factor in the last 10 minutes.
// run() makes the call, and on either refusal asks for the password or a
// code in the slot it is given, proves it (POST /auth/reauthenticate,
// POST /auth/second-factor/verify) and makes the call again. Cancel ends
// with an ApiError of code "cancelled", which the caller says or ignores.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  // A call that asked for a password and then for a code is made three times at most.
  const TRIES = 3;

  const ASK = {
    reauthentication_required: {
      title: "Confirm with your password",
      hint: (what) => what + " needs your password again on this browser (it counts for 10 minutes).",
      label: "Password", type: "password", autocomplete: "current-password",
      prove: (value) => M.api.post("/auth/reauthenticate", { password: value }),
      wrong: (err) => (err.code === "invalid" && err.details && err.details.fields && err.details.fields.password
        ? "That is not your password." : err.code === "rate_limited" ? "Too many wrong passwords; wait a few minutes." : null),
    },
    step_up_required: {
      title: "Confirm with your second factor",
      hint: (what) => what + " needs your second factor: enter the code from your authenticator app, or a recovery code (it counts for 10 minutes).",
      label: "Code", type: "text", autocomplete: "one-time-code",
      // A code may be typed with spaces ("482 913"): six digits without them are a code (§2.8.1).
      prove: (value) => {
        const digits = value.replace(/\s+/g, "");
        return M.api.post("/auth/second-factor/verify", /^\d{6}$/.test(digits) ? { code: digits } : { recovery_code: value });
      },
      wrong: (err) => (err.code === "code_invalid" ? "That code is not valid." : err.code === "rate_limited" ? "Too many wrong codes; wait a few minutes." : null),
    },
  };

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
      const submit = h("button", { type: "submit" }, "Confirm");
      const done = () => { open.delete(slot); clear(slot); slot.hidden = true; };
      open.set(slot, () => { done(); reject(new M.api.ApiError("Cancelled", 0, "", "cancelled")); });
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
            error.textContent = a.wrong(err) || "Not confirmed: " + err.message;
            input.value = "";
            input.focus();
          }
        },
      },
      h("h4", { class: "step-up-title" }, a.title),
      h("p", { class: "hint" }, a.hint(what || "This")),
      h("label", { for: id }, a.label), input, submit,
      h("button", { type: "button", onclick: () => { done(); reject(new M.api.ApiError("Cancelled", 0, "", "cancelled")); } }, "Cancel"),
      error);
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
        await ask(slot, reason, what);
      }
    }
  }

  M.stepUp = { run };
})(window.Maity);
