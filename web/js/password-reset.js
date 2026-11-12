// A forgotten password (docs/api.md §2.10, tsk-yksxdpd2pk0m): "Forgot password?" under the
// login's password field asks for an address, and the mailed link opens /sign-in/reset, where a
// new password is set. The page signs nobody in: it ends every session and links to the login.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const PASSWORD_MIN = 12;
  const PAGE = "/sign-in/reset";

  // The bar of a page without a project, as /register has it: the lockup and the theme.
  function bar(header) {
    append(clear(header), h("div", { class: "bar" }, M.brandTitle ? M.brandTitle(undefined, "div") : null,
      M.api.source === "fixtures" ? h("span", { class: "source" }, M.t("header.fixtures")) : null, M.themeMenu ? M.themeMenu() : null));
  }

  // The hub's refusals of the three calls in words. code_invalid never says which reason applies
  // (§2.10), and neither does the page.
  function said(err) {
    const d = (err && err.details) || {};
    if (err.code === "forbidden" && d.reason === "method_disabled") return { message: M.t("reset.disabled") };
    if (err.code === "rate_limited") return { message: M.t("reset.rate_limited", { minutes: M.secondFactor.minutes(d.retry_after) }) };
    if (err.code === "invalid" && d.fields && d.fields.new === "too_short") return { message: M.t("reset.short_password", { min: PASSWORD_MIN }) };
    return err;
  }

  // "Forgot password?" (§2.6.7): a button under the password field that opens a form for the
  // address. The answer is one sentence for every address, as the hub's is (§2.10).
  // address(): what the login's address field holds, to start from.
  function forgot(address) {
    const panel = h("section", { class: "sign-in-forgot", "aria-label": M.t("reset.forgot") });
    const status = M.statusLine();
    const input = h("input", { id: "reset-address", type: "email", autocomplete: "email", required: true });
    const send = h("button", { type: "submit", class: "btn btn-secondary" }, M.t("reset.send"));
    const form = h("form", {
      class: "sign-in-form reset-ask",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const value = input.value.trim();
        if (!value) { status.fail(M.t("reset.not_sent"), { message: M.t("reset.need_address") }); input.focus(); return; }
        send.disabled = true;
        status.busy(M.t("reset.sending"));
        let answer;
        try {
          answer = await M.api.post("/auth/password-reset", { address: value });
        } catch (err) {
          send.disabled = false;
          status.fail(M.t("reset.not_sent"), said(err));
          return;
        }
        send.disabled = false;
        status.done();
        const minutes = Math.max(1, Math.round(((answer && answer.expires_in) || 1800) / 60));
        append(status.el, h("span", { class: "ok" }, M.t("reset.sent", { minutes })));
      },
    },
    h("h3", { id: "reset-ask-title" }, M.t("reset.ask.title")),
    h("p", { class: "hint", id: "reset-address-hint" }, M.t("reset.ask.hint")),
    h("label", { for: "reset-address" }, M.t("reset.address")), input, send, status.el);
    input.setAttribute("aria-describedby", "reset-address-hint");
    const open = h("button", { type: "button", class: "link-button reset-open", "aria-expanded": "false",
      onclick: () => {
        open.setAttribute("aria-expanded", "true");
        open.hidden = true;
        input.value = address ? address() : "";
        append(panel, form);
        input.focus();
      } }, M.t("reset.forgot"));
    append(panel, open);
    return panel;
  }

  // The link's token: in the fragment over http(s), which no browser sends to a server; in
  // fixture mode the fragment holds the route, so the token is its query there. Read once, then
  // gone from the address bar, as the device code and the mail factor's token are.
  function tokenFromAddress() {
    const at = M.route.current();
    const t = M.route.fixture ? at.query.get("token") : at.fragment;
    M.route.dropFragment();
    return t || null;
  }

  // /sign-in/reset#<token>: read before any session, signed in or not, since the reset ends
  // every session anyway and signs nobody in.
  async function page(main, header) {
    const token = tokenFromAddress();
    bar(header);
    document.title = M.t("reset.title") + " · Maity";
    const box = h("article", { class: "reset-page" });
    const legal = M.legal ? M.legal.links() : null;
    append(clear(main), M.authPages.door(null, [box, legal]));
    M.siteChrome.enter(PAGE, () => { if (legal) legal.remove(); });
    const status = M.statusLine();
    const heading = h("h1", { tabindex: "-1" }, M.t("reset.title"));
    append(box, heading, status.el);
    const newLink = () => h("p", null, M.tn("reset.new_link", { link: h("a", { href: "/login" }, M.t("reset.new_link.link")) }));
    // A link that does not work, for whatever reason: one sentence, and the way to a new one.
    const dead = () => {
      clear(box);
      append(box, heading, h("p", { class: "reset-dead" }, M.t("reset.dead")), newLink());
    };
    if (!token) { dead(); return; }
    status.busy(M.t("reset.reading"));
    let who;
    try {
      who = await M.api.post("/auth/password-reset/check", { token });
    } catch (err) {
      if (err.code === "code_invalid") { dead(); return; }
      status.fail(M.t("reset.read_failed"), said(err));
      return;
    }
    status.done();
    form(box, heading, token, who, newLink);
  }

  function form(box, heading, token, who, newLink) {
    const totp = who.factor === "totp";
    const password = h("input", { id: "reset-password", type: "password", autocomplete: "new-password", required: true, minlength: String(PASSWORD_MIN) });
    const repeat = h("input", { id: "reset-repeat", type: "password", autocomplete: "new-password", required: true });
    // TOTP enrolled: its code, or a recovery code instead (§2.10, as at the sign-in's step).
    let recovery = false;
    const code = h("input", { id: "reset-code", autocomplete: "one-time-code", spellcheck: "false", inputmode: "numeric", "aria-describedby": "reset-code-hint" });
    const codeLabel = h("label", { for: "reset-code" });
    const codeHint = h("p", { class: "hint", id: "reset-code-hint" });
    const swap = h("button", { type: "button", class: "link-button reset-code-swap", onclick: () => { recovery = !recovery; drawCode(); code.value = ""; code.focus(); } });
    function drawCode() {
      codeLabel.textContent = recovery ? M.t("reset.recovery.label") : M.t("reset.code.label");
      codeHint.textContent = recovery ? M.t("reset.recovery.hint") : M.t("reset.code.hint");
      swap.textContent = recovery ? M.t("reset.code.use") : M.t("reset.recovery.use");
      if (recovery) code.removeAttribute("inputmode"); else code.setAttribute("inputmode", "numeric");
    }
    drawCode();
    const status = M.statusLine();
    const submit = h("button", { type: "submit", class: "btn btn-primary" }, M.t("reset.submit"));
    const f = h("form", {
      class: "reset-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if ([...password.value].length < PASSWORD_MIN) { status.fail(M.t("reset.not_set"), { message: M.t("reset.short_password", { min: PASSWORD_MIN }) }); password.focus(); return; }
        if (password.value !== repeat.value) { status.fail(M.t("reset.not_set"), { message: M.t("reset.passwords_differ") }); repeat.focus(); return; }
        const body = { token, new: password.value };
        if (totp) {
          const value = code.value.trim();
          if (!value) { status.fail(M.t("reset.not_set"), { message: recovery ? M.t("reset.recovery.need") : M.t("reset.code.need") }); code.focus(); return; }
          if (recovery) body.recovery_code = value;
          else body.code = value.replace(/\s+/g, "");
        }
        submit.disabled = true;
        status.busy(M.t("reset.setting"));
        try {
          await M.api.post("/auth/password-reset/complete", body);
        } catch (err) {
          submit.disabled = false;
          if (err.code === "code_invalid") {
            // A wrong code and a dead link are one answer (§2.10). With a code asked, it may be
            // the code: the form stays, the code is cleared; without one, the link is dead.
            if (!totp) { password.value = ""; repeat.value = ""; status.fail(M.t("reset.not_set"), { message: M.t("reset.dead_reason") }); append(status.el, " ", newLink()); return; }
            code.value = "";
            status.fail(M.t("reset.not_set"), { message: M.t("reset.code_or_link") });
            code.focus();
            return;
          }
          status.fail(M.t("reset.not_set"), said(err));
          return;
        }
        password.value = ""; repeat.value = ""; code.value = "";
        clear(box);
        const done = h("h1", { tabindex: "-1" }, M.t("reset.done.title"));
        append(box, done, h("p", null, M.t("reset.done.sessions")),
          h("p", null, h("a", { class: "btn btn-primary", href: "/login" }, M.t("reset.done.sign_in"))));
        window.setTimeout(() => done.focus(), 0);
      },
    },
    who.factor === "email" ? h("p", { class: "flag reset-mail-factor" }, M.tn("reset.mail_factor", {
      link: h("a", { href: "/account/security" }, M.t("reset.mail_factor.link")) })) : null,
    h("label", { for: "reset-password" }, M.t("reset.password", { min: PASSWORD_MIN })), password,
    h("label", { for: "reset-repeat" }, M.t("reset.repeat")), repeat,
    totp ? [codeLabel, codeHint, code, swap] : null,
    submit, status.el,
    h("p", { class: "muted" }, M.t("reset.explain")));
    // "Set a new password for <display name> (<handle>)" (§2.10), once the link is read.
    heading.textContent = M.t("reset.for", { name: who.display_name, handle: who.handle });
    append(box, f);
    window.setTimeout(() => password.focus(), 0);
  }

  M.passwordReset = { forgot, page, PAGE };
})(window.Maity);
