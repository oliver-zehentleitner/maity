// Registration (docs/api.md §2.7.1): /register?next=…, signed out. The
// form asks for the address and a password; the hub answers the same for
// every address, and the account is made from the link it mails. Offered
// where the instance registers (GET /auth/methods), or where the
// invitation the person comes from admits them (§3.4).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const PASSWORD_MIN = 12;
  // The bar of a page without a project: the lockup and the theme.
  function bar(header) {
    append(clear(header), h("div", { class: "bar" }, M.brandTitle ? M.brandTitle() : null,
      M.api.source === "fixtures" ? h("span", { class: "source" }, "Fixtures") : null, M.themeMenu ? M.themeMenu() : null));
  }

  async function register(main, header, next) {
    // Signed in, there is nothing to register: on to next, or the start.
    const session = await M.api.get("/auth/session").then(() => true, () => false);
    if (session) { M.route.go(next || "/all", { replace: true }); return; }
    bar(header);
    document.title = "Create an account · Maity";
    const box = h("article", { class: "register door" });
    // The legal pages that are set, under the form (§16.7.1).
    append(clear(main), box, M.legal ? M.legal.links() : null);
    const signIn = next ? "/login?next=" + encodeURIComponent(next) : "/login";
    // May this person register here? The instance's mode (§2.6.1), or an
    // address-bound invitation that admits (§3.4) when they come from one.
    let methods = null;
    let invitation = null;
    try {
      if (await M.api.hubHas("GET", "/auth/methods")) methods = await M.api.get("/auth/methods");
      // Only a token of the hub's form (§3.4) is asked about.
      const invited = next && /^\/invite\/([A-Za-z0-9_-]{22})$/.exec(next);
      if (invited) invitation = await M.api.get("/invitations/" + encodeURIComponent(invited[1])).catch(() => null);
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, "Could not read how this hub registers: " + err.message));
      return;
    }
    const allowed = (methods && methods.registration) || (invitation && invitation.registration === "sign_in_or_register");
    append(box, h("h2", null, "Create an account"));
    if (!allowed) {
      append(box, h("p", null, "This hub does not create new accounts on request."),
        h("p", null, "If you have an account, ", h("a", { href: signIn }, "sign in"), "."));
      return;
    }
    const address = h("input", { id: "register-address", type: "email", autocomplete: "email", required: true });
    const password = h("input", { id: "register-password", type: "password", autocomplete: "new-password", required: true, minlength: String(PASSWORD_MIN) });
    const repeat = h("input", { id: "register-repeat", type: "password", autocomplete: "new-password", required: true });
    const status = M.statusLine();
    const submit = h("button", { type: "submit", class: "primary" }, "Send me the link");
    const form = h("form", {
      class: "register-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (!address.value.trim()) { status.fail("Not sent: ", { message: "your address is needed" }); address.focus(); return; }
        if ([...password.value].length < PASSWORD_MIN) { status.fail("Not sent: ", { message: "a password has at least " + PASSWORD_MIN + " characters" }); password.focus(); return; }
        if (password.value !== repeat.value) { status.fail("Not sent: ", { message: "the two passwords differ" }); repeat.focus(); return; }
        submit.disabled = true;
        status.busy("Sending…");
        let answer;
        try {
          answer = await M.api.post("/auth/register", Object.assign({ address: address.value.trim(), password: password.value }, next ? { next } : {}));
        } catch (err) {
          submit.disabled = false;
          status.fail("Not sent: ", registerWords(err));
          return;
        }
        // The same answer for every address (§2.7.1): what comes next is in the mail.
        const hours = Math.round(((answer && answer.expires_in) || 86400) / 3600);
        clear(box);
        const done = h("h2", { tabindex: "-1" }, "Check your mail");
        append(box, done,
          h("p", null, "If " + address.value.trim() + " may register here, a link is on its way to it. It works for " + hours + " hours."),
          h("p", null, "Follow it, enter the password you just chose, and pick your handle and the name others see."
            + (next ? " You then come back to where you were." : "")),
          h("p", { class: "muted" }, "No mail? Look in the spam folder; a second request from here replaces the first."));
        window.setTimeout(() => done.focus(), 0);
      },
    },
    invitation && invitation.address_bound ? h("p", { class: "hint" }, "Use the address the invitation was sent to: it only opens for that one.") : null,
    h("label", { for: "register-address" }, "Your address"), address,
    h("label", { for: "register-password" }, "Password (at least " + PASSWORD_MIN + " characters)"), password,
    h("label", { for: "register-repeat" }, "The password again"), repeat,
    submit, status.el,
    h("p", { class: "muted" }, "Have an account? ", h("a", { href: signIn }, "Sign in"), "."));
    append(box, h("p", { class: "muted" }, "We send a link to your address; the account is made only once you follow it."), form);
  }

  function registerWords(err) {
    const d = err.details || {};
    if (d.reason === "registration_closed") return { message: "this hub does not create accounts right now" };
    // Per source an hour, the instance's breaker a minute (§2.7.3): no promise of either.
    if (err.code === "rate_limited") return { message: "too many requests just now; try again later" };
    if (d.fields) return { message: Object.entries(d.fields).map(([f, r]) => f + ": " + r).join("; ") };
    return err;
  }

  M.register = { page: register };
})(window.Maity);
