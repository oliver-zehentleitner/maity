// The second step of a sign-in (docs/api.md §2.8.2, §2.8.8, tsk-ekpb0pvgw4bh): after
// the first factor the session owes the second factor, and GET /auth/session says how
// (`via`): the code of the authenticator app or a recovery code (`totp`), or the link or
// the code of the mail the hub sent at the first factor (`email`), with Send again. The
// mail's link, /sign-in/second-factor/email#<token>, is posted from the page: only the
// browser that did the first factor holds the session it completes, so a link opened
// anywhere else says where to open it instead.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const MAIL_LINK = "/sign-in/second-factor/email";

  const isMailLink = () => M.route.current().path === MAIL_LINK;

  // The mail's token: in the fragment over http(s), which no browser sends to a server;
  // in fixture mode the fragment holds the route, so the token is its query there. Read
  // once, then gone from the address, as the device code is (js/device-sign-in.js).
  function tokenFromAddress() {
    if (!isMailLink()) return null;
    const at = M.route.current();
    const t = M.route.fixture ? at.query.get("token") : at.fragment;
    M.route.dropFragment();
    return t || null;
  }

  // A wait in whole minutes, at least one: the hub counts seconds, a person reads minutes.
  const minutes = (seconds) => Math.max(1, Math.ceil(Number(seconds || 0) / 60));

  // The hub's refusals of the step in words (§2.8.2, §2.8.6, §2.8.8).
  function said(err, email) {
    if (err.code === "code_invalid") return { message: email ? M.t("sf.wrong.email") : M.t("sf.wrong.totp") };
    if (err.code === "rate_limited") return { message: M.t("sf.rate_limited", { minutes: minutes(err.details && err.details.retry_after) }) };
    if (err.code === "mail_not_configured") return { message: M.t("sf.mail.not_configured") };
    if (err.code === "address_unverified") return { message: M.t("sf.mail.address_lost") };
    return err;
  }

  // What the mail of the step is doing, as GET /auth/session says it (`mail`), to whom
  // (`address_hint` where the hub gives it; until then "your address").
  function mailWords(session) {
    const to = session.address_hint ? M.t("sf.mail.to_hint", { address: session.address_hint }) : M.t("sf.mail.to_yours");
    if (session.mail === "rate_limited") return M.t("sf.mail.rate_limited", { minutes: minutes(session.retry_after) });
    if (session.mail === "unavailable") return M.t("sf.mail.unavailable");
    return M.t("sf.mail.sent", { to });
  }

  // session: GET /auth/session's answer; done(next): the sign-in is complete, go on;
  // signOut(): end the second-factor session, back to the first factor.
  function page(main, session, done, signOut) {
    document.title = M.t("sf.title") + " · Maity";
    const email = session.via === "email";
    const status = M.statusLine();
    const input = h("input", { id: "sf-code", autocomplete: "one-time-code", spellcheck: "false", "aria-describedby": "sf-hint" });
    const submit = h("button", { type: "submit", class: "primary" }, M.t("sf.verify"));
    const lead = h("p", { id: "sf-hint", class: "sf-lead" });
    const draw = (s) => { lead.textContent = email ? mailWords(s) : M.t("sf.totp.lead"); };
    draw(session);

    async function verify(body) {
      status.busy(M.t("sf.verifying"));
      submit.disabled = true;
      let answer;
      try {
        answer = await M.api.post("/auth/second-factor/verify", body);
      } catch (err) {
        submit.disabled = false;
        status.fail(M.t("sf.not_verified"), said(err, email));
        input.value = "";
        input.focus();
        return;
      }
      status.done();
      done(answer && answer.next);
    }

    // Send again (§2.8.8): a new mail voids the earlier link and code; the page reads
    // the session again for what the hub says of the mail now.
    async function resend() {
      status.busy(M.t("sf.mail.sending"));
      try {
        await M.api.post("/auth/second-factor/email", {});
        draw(await M.api.get("/auth/session"));
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("sf.mail.sent_again")));
      } catch (err) {
        status.fail(M.t("sf.mail.not_sent"), said(err, true));
      }
    }

    const form = h("form", {
      class: "door second-factor",
      onsubmit: (e) => {
        e.preventDefault();
        const value = input.value.trim();
        if (!value) { input.focus(); return; }
        // Six digits, spaces ignored, are a code (§2.8.1); anything else a recovery code.
        const digits = value.replace(/\s+/g, "");
        verify(email ? { email_code: digits } : /^\d{6}$/.test(digits) ? { code: digits } : { recovery_code: value });
      },
    },
    h("h2", null, M.t("sf.title")), lead,
    h("label", { for: "sf-code" }, email ? M.t("sf.email.label") : M.t("sf.totp.label")), input,
    submit,
    email ? h("button", { type: "button", class: "sf-resend", onclick: resend }, M.t("sf.mail.send_again")) : null,
    h("button", { type: "button", class: "link-button sf-sign-out", onclick: signOut }, M.t("sf.sign_out")),
    status.el);
    append(clear(main), form);

    // The mail's link opened in this browser: posted at once, the human typed nothing.
    const token = email ? tokenFromAddress() : null;
    if (token) verify({ email_token: token });
    else window.setTimeout(() => input.focus(), 0);
  }

  // The mail's link opened in a browser that holds no second-factor session for it: it
  // completes nothing here (§2.8.8), so the page says where to open it.
  function elsewhere(main, signedIn) {
    document.title = M.t("sf.title") + " · Maity";
    M.route.dropFragment();
    append(clear(main), h("section", { class: "door second-factor-elsewhere" },
      h("h2", null, M.t("sf.title")),
      h("p", null, M.t("sf.elsewhere")),
      signedIn ? h("a", { href: "/all" }, M.t("sf.elsewhere.dashboard")) : h("a", { href: "/login" }, M.t("sf.elsewhere.sign_in"))));
  }

  M.secondFactor = { page, elsewhere, isMailLink };
})(window.Maity);
