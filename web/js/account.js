// The signed-in human's account (#/account): who they are, and changing
// the password (docs/api.md §2.1, POST /auth/password). A change ends
// every other session of this human; this one stays signed in.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append } = M.dom;

  // The hub's minimum, counted in characters as the hub counts them.
  const MIN_LENGTH = 12;

  M.views.account = async function (ctx, root) {
    const field = (id, label, autocomplete, hint) => {
      const input = h("input", { id, type: "password", autocomplete, required: true, "aria-describedby": id + "-error" });
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      return { input, error, nodes: [h("label", { for: id }, label), input, hint ? h("p", { class: "hint" }, hint) : null, error] };
    };
    const current = field("password-current", "Current password", "current-password");
    const fresh = field("password-new", "New password", "new-password", "At least " + MIN_LENGTH + " characters.");
    const repeat = field("password-repeat", "New password again", "new-password");
    const all = [current, fresh, repeat];
    const status = M.statusLine();

    const showErrors = (errors) => {
      all.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
      errors.forEach(([f, text]) => { f.error.textContent = text; f.input.setAttribute("aria-invalid", "true"); });
      if (errors.length) errors[0][0].input.focus();
    };

    const submit = h("button", { type: "submit" }, "Change password");
    const form = h("form", {
      class: "project-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const errors = [];
        if (!current.input.value) errors.push([current, "Required."]);
        if ([...fresh.input.value].length < MIN_LENGTH) errors.push([fresh, "At least " + MIN_LENGTH + " characters."]);
        else if (fresh.input.value !== repeat.input.value) errors.push([repeat, "The two new passwords differ."]);
        showErrors(errors);
        if (errors.length) { status.done(); return; }
        submit.disabled = true;
        status.busy("Changing…");
        try {
          await M.api.post("/auth/password", { current: current.input.value, new: fresh.input.value });
          all.forEach((f) => { f.input.value = ""; });
          status.done();
          append(status.el, h("span", { class: "ok" },
            "Password changed. Every other session of yours was signed out; this one stays signed in."));
        } catch (err) {
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields && (fields.current || fields.new)) {
            showErrors([
              fields.current ? [current, fields.current === "mismatch" ? "This is not your current password." : String(fields.current)] : null,
              fields.new ? [fresh, fields.new === "too_short" ? "At least " + MIN_LENGTH + " characters." : String(fields.new)] : null,
            ].filter(Boolean));
            status.done();
          } else if (err.code === "rate_limited") {
            status.fail("Not changed: ", { message: "too many wrong passwords; wait a moment and try again" });
          } else {
            status.fail("Not changed: ", err);
          }
        } finally {
          submit.disabled = false;
        }
      },
    }, current.nodes, fresh.nodes, repeat.nodes, submit, status.el);

    append(root, h("h2", null, "Your account"),
      h("dl", { class: "facts" },
        h("dt", null, "Name"), h("dd", null, ctx.me.display_name),
        h("dt", null, "Handle"), h("dd", null, "@" + ctx.me.handle)),
      h("h3", null, "Change password"),
      h("p", { class: "muted" }, "Changing it signs out every other browser and device where you are signed in."),
      form);
  };
})(window.Maity);
