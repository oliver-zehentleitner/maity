// Signing in without a password (docs/api.md §2.6). On the login page, as
// GET /auth/methods offers them: "Have a code?" for the new device (§2.6.2)
// and "Email me a sign-in link" (§2.6.3). On a signed-in device, "Sign in
// another device" (/account/sign-in-device): the code, its QR, a countdown
// and then the approval, which leads with what the hub observed, labels
// what the device claims, and has the human pick the number the device
// shows; Deny is the default and there is no plain Approve (§2.6.7).
// Both sides read their state with wait=0 every POLL_MS on the dashboard's
// timers, which stop when the page changes (context/refresh.md).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const POLL_MS = 2000;
  const ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ";

  // As the hub reads a code: case ignored, hyphens and spaces dropped, I and
  // L as 1, O as 0 (§2.6.2). null when it is not 12 characters of the alphabet.
  const CODE_LENGTH = 12;
  // The mail's code (§2.6.3): this many digits, said and checked from one number.
  const MAIL_DIGITS = 6;
  const MAIL_CODE = new RegExp("^\\d{" + MAIL_DIGITS + "}$");
  function normalCode(text) {
    const c = String(text || "").toUpperCase().replace(/[\s-]/g, "").replace(/[IL]/g, "1").replace(/O/g, "0");
    return c.length === CODE_LENGTH && [...c].every((ch) => ALPHABET.includes(ch)) ? c : null;
  }
  // Three groups of four, as the hub shows it: K7QM-4XPR-9D2F.
  const grouped = (c) => (c.match(/.{1,4}/g) || []).join("-");

  // "4:07" until the hub's expiry, by the hub's clock.
  function left(expiresAt) {
    const s = Math.max(0, Math.round((Date.parse(expiresAt) - M.api.now()) / 1000));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  // One read at a time, and none once the flow has ended.
  function poller(every, read) {
    let busy = false;
    let over = false;
    every(POLL_MS, async () => {
      if (busy || over) return;
      busy = true;
      try { await read(); } finally { busy = false; }
    });
    return () => { over = true; };
  }

  // What a refusal means here, in words.
  function said(err) {
    if (err.code === "code_invalid") return { message: M.t("device.refused.code_invalid") };
    if (err.code === "rate_limited") return { message: M.t("device.refused.rate") };
    if (err.details && err.details.reason === "method_disabled") return { message: M.t("device.refused.disabled") };
    return err;
  }

  // Where to go once signed in: the `next` the hub kept, if it is one of
  // the dashboard's own paths (§2.6.5).
  function goNext(next) {
    M.route.go((M.safeNext && M.safeNext(next)) || "/", { replace: true });
  }

  // ---- the login page ------------------------------------------------------

  // Below the password form. `every` runs on the login page's timers;
  // `signedIn` draws the dashboard once a session exists.
  function loginOptions(every, signedIn) {
    const box = h("div", { class: "sign-in-options" });
    M.api.get("/auth/methods")
      .then((methods) => {
        const prefilled = codeFromAddress();
        const next = M.signInNext ? M.signInNext() : null;
        append(box,
          methods.device_code ? codeEntry(every, signedIn, prefilled) : null,
          methods.email_link ? mailLink(signedIn) : null,
          // §2.7: offered only where the instance registers.
          methods.registration ? h("p", { class: "register-link" }, M.tn("device.register", {
            link: h("a", { href: "/register" + (next ? "?next=" + encodeURIComponent(next) : "") }, M.t("device.register.link")) })) : null);
      }, () => {});
    return box;
  }

  // /sign-in/code#c=K7QM4XPR9D2F, the QR's URL (§2.6.2, §16.11): the code in
  // the fragment, never sent to the hub; the field filled in, sent only on
  // the human's tap. Read once, then gone from the address: a later drawing
  // of the login box finds no code and leaves the field empty, by design (a
  // code in the address bar or the history is one more place to read it
  // from). In fixture mode the fragment holds the route, so the code is its
  // query there.
  function codeFromAddress() {
    const at = M.route.current();
    if (at.path !== "/sign-in/code") return null;
    const c = M.route.fixture ? at.query.get("c") : new URLSearchParams(at.fragment).get("c");
    M.route.dropFragment();
    return c ? normalCode(c) : null;
  }

  function codeEntry(every, signedIn, prefilled) {
    const panel = h("section", { class: "sign-in-code", "aria-labelledby": "sign-in-code-title" });
    const status = M.statusLine();
    const input = h("input", { id: "device-code", autocomplete: "off", autocapitalize: "characters", spellcheck: "false",
      placeholder: "XXXX-XXXX-XXXX", "aria-describedby": "device-code-hint" });
    const submit = h("button", { type: "submit", class: "primary" }, M.t("device.code.continue"));
    const form = h("form", {
      class: "sign-in-form",
      onsubmit: (e) => {
        e.preventDefault();
        const code = normalCode(input.value);
        if (!code) { status.fail(M.t("device.not_sent"), { message: M.t("device.code.format", { example: "K7QM-4XPR-9D2F" }) }); input.focus(); return; }
        redeem(code);
      },
    },
    h("label", { for: "device-code" }, M.t("device.code.label")),
    h("p", { class: "hint", id: "device-code-hint" }, M.t("device.code.hint")),
    input, submit, status.el);
    const open = h("button", { type: "button", class: "link-button", "aria-expanded": "false",
      onclick: () => { showForm(); input.focus(); } }, M.t("device.code.open"));

    function showForm() {
      open.setAttribute("aria-expanded", "true");
      append(clear(panel), h("h3", { id: "sign-in-code-title" }, M.t("device.code.title")), form);
    }
    async function redeem(code) {
      submit.disabled = true;
      status.busy(M.t("device.sending"));
      let answer;
      try {
        const next = M.signInNext ? M.signInNext() : null;
        answer = await M.api.post("/auth/device-login", next ? { code, next } : { code });
      } catch (err) {
        submit.disabled = false;
        status.fail(M.t("device.not_signed_in"), said(err));
        return;
      }
      waiting(answer);
    }
    // Waiting for the other device: the match number and the time left.
    function waiting(answer) {
      const countdown = h("span", { class: "countdown" }, left(answer.expires_at));
      const note = M.statusLine();
      let expiresAt = answer.expires_at;
      const again = h("button", { type: "button", onclick: () => { stop(); input.value = ""; submit.disabled = false; status.done(); showForm(); input.focus(); } }, M.t("device.wait.another"));
      const view = h("div", { class: "device-waiting", role: "status" },
        h("h3", { id: "sign-in-code-title" }, M.t("device.wait.title")),
        h("p", null, M.t("device.wait.pick")),
        h("p", { class: "match-number", "aria-label": M.t("device.wait.number", { number: String(answer.match_number) }) }, String(answer.match_number)),
        h("p", { class: "muted" }, M.tn("device.expires", { time: countdown })),
        note.el, again);
      append(clear(panel), view);
      every(1000, () => { countdown.textContent = left(expiresAt); });
      const stop = poller(every, async () => {
        let now;
        try {
          now = await M.api.get("/auth/device-login?wait=0");
        } catch (err) {
          if (err.status === 404) { stop(); note.fail("", { message: M.t("device.wait.gone") }); }
          return;
        }
        expiresAt = now.expires_at || expiresAt;
        if (now.status === "approved") { stop(); approved(now.account); }
        else if (now.status === "denied") { stop(); note.fail("", { message: M.t("device.wait.denied") }); }
        else if (now.status === "expired") { stop(); note.fail("", { message: M.t("device.wait.expired") }); }
      });
    }
    // Approved: only now the account (§2.6.2), then this browser's session.
    async function approved(account) {
      const status2 = M.statusLine();
      append(clear(panel), h("div", { class: "device-approved", role: "status" },
        h("h3", { id: "sign-in-code-title" }, M.t("device.approved.title")),
        account ? h("p", { class: "device-account" }, M.avatar(Object.assign({ id: account.handle }, account), 32), " ",
          M.tn("device.approved.as", { name: h("strong", null, account.display_name), handle: account.handle })) : null,
        status2.el));
      status2.busy(M.t("device.signing_in"));
      try {
        const done = await M.api.post("/auth/device-login/complete", {});
        goNext(done.next);
        signedIn();
      } catch (err) {
        status2.fail(M.t("device.not_signed_in"), said(err));
      }
    }

    if (prefilled) { input.value = grouped(prefilled); showForm(); window.setTimeout(() => submit.focus(), 0); }
    else append(panel, open);
    return panel;
  }

  // A link by mail, and the six-digit code for when the mail is read elsewhere.
  function mailLink(signedIn) {
    const panel = h("section", { class: "sign-in-mail", "aria-labelledby": "sign-in-mail-title" });
    const status = M.statusLine();
    const address = h("input", { id: "sign-in-address", type: "email", autocomplete: "email", required: true });
    const ask = h("form", {
      class: "sign-in-form",
      onsubmit: async (e) => {
        e.preventDefault();
        if (!address.value.trim()) { address.focus(); return; }
        status.busy(M.t("device.sending"));
        try {
          const next = M.signInNext ? M.signInNext() : null;
          await M.api.post("/auth/email-link", next ? { address: address.value.trim(), next } : { address: address.value.trim() });
          status.done();
          codeForm();
        } catch (err) {
          status.fail(M.t("device.not_sent"), said(err));
        }
      },
    },
    h("h3", { id: "sign-in-mail-title" }, M.t("device.mail.title")),
    h("label", { for: "sign-in-address" }, M.t("device.mail.address")), address,
    h("button", { type: "submit" }, M.t("device.mail.send")), status.el);
    function codeForm() {
      const code = h("input", { id: "sign-in-mail-code", inputmode: "numeric", autocomplete: "one-time-code", "aria-describedby": "sign-in-mail-sent" });
      const status2 = M.statusLine();
      append(clear(panel), h("form", {
        class: "sign-in-form",
        onsubmit: async (e) => {
          e.preventDefault();
          const digits = code.value.replace(/\s/g, "");
          if (!MAIL_CODE.test(digits)) { status2.fail(M.t("device.not_sent"), { message: M.t("device.mail.digits", { count: MAIL_DIGITS }) }); code.focus(); return; }
          status2.busy(M.t("device.signing_in"));
          try {
            const done = await M.api.post("/auth/email-code", { code: digits });
            goNext(done.next);
            signedIn();
          } catch (err) {
            status2.fail(M.t("device.not_signed_in"), err.code === "code_invalid" ? { message: M.t("device.mail.no_match") } : said(err));
          }
        },
      },
      h("h3", { id: "sign-in-mail-title" }, M.t("device.mail.check")),
      h("p", { id: "sign-in-mail-sent", role: "status" }, M.t("device.mail.sent")),
      h("label", { for: "sign-in-mail-code" }, M.t("device.mail.code", { count: MAIL_DIGITS })), code,
      h("button", { type: "submit", class: "primary" }, M.t("device.mail.sign_in")), status2.el));
      code.focus();
    }
    const open = h("button", { type: "button", class: "link-button", "aria-expanded": "false",
      onclick: () => { append(clear(panel), ask); address.focus(); } }, M.t("device.mail.send"));
    append(panel, open);
    return panel;
  }

  // ---- the signed-in device: /account/sign-in-device ----------------------

  async function anotherDevice(ctx, root) {
    const heading = h("h2", { tabindex: "-1" }, M.t("device.other.title"));
    const stage = h("div", { class: "device-stage" });
    append(root, heading,
      h("p", { class: "muted" }, M.t("device.other.intro")),
      stage);
    window.setTimeout(() => heading.focus(), 0);
    await start(ctx, stage);
  }

  // The QR of the code's URL; the code and Cancel stand without it.
  function qrOf(url) {
    try {
      return h("div", { class: "qr-box" }, M.qr.svg(url, 200));
    } catch (err) {
      return h("p", { class: "muted" }, M.t("device.other.no_qr"));
    }
  }

  async function start(ctx, stage) {
    const status = M.statusLine();
    append(clear(stage), status.el);
    status.busy(M.t("device.other.making"));
    let made;
    try {
      made = await M.api.post("/auth/device-codes", {});
    } catch (err) {
      if (err.details && err.details.reason === "method_disabled") { append(clear(stage), h("p", { class: "muted" }, M.t("device.other.disabled"))); return; }
      status.fail(M.t("device.other.no_code"), said(err));
      return;
    }
    const code = normalCode(made.code) || made.code;
    const countdown = h("span", { class: "countdown" }, left(made.expires_at));
    const fresh = () => h("button", { type: "button", onclick: () => { stop(); start(ctx, stage); } }, M.t("device.other.new_code"));
    const cancel = h("button", { type: "button", onclick: async () => {
      stop();
      try { await M.api.del("/auth/device-codes/" + encodeURIComponent(made.id)); } catch (err) { /* it ends with its expiry anyway */ }
      ended(M.t("device.other.cancelled"));
    } }, M.t("device.other.cancel"));
    const view = h("div", { class: "device-code" },
      h("p", { class: "device-code-text", "aria-label": M.t("device.other.code_label", { code: [...code.replace("-", "")].join(" ") }) }, grouped(code.replace("-", ""))),
      qrOf(made.url),
      h("p", { class: "muted" }, M.tn("device.other.expires", { time: countdown })),
      h("div", { class: "actions" }, cancel));
    append(clear(stage), view);
    let expiresAt = made.expires_at;
    ctx.every(1000, () => { countdown.textContent = left(expiresAt); });
    let shown = null;
    const stop = poller(ctx.every, async () => {
      let now;
      try {
        now = await M.api.get("/auth/device-codes/" + encodeURIComponent(made.id) + "?wait=0");
      } catch (err) {
        if (err.status === 404) { stop(); ended(M.t("device.other.gone")); }
        return;
      }
      expiresAt = now.expires_at || expiresAt;
      if (now.status === "redeemed" && shown !== "redeemed") { shown = "redeemed"; approval(now); }
      else if (now.status === "approved" || now.status === "used") { stop(); ended(now.status === "used" ? M.t("device.other.used") : M.t("device.other.approved"), true); }
      else if (now.status === "denied") { stop(); ended(M.t("device.other.denied")); }
      else if (now.status === "expired") { stop(); ended(M.t("device.other.expired")); }
    });

    function ended(words, good) {
      append(clear(stage), h("p", { class: good ? "ok" : "muted", role: "status" }, words), good ? null : h("div", { class: "actions" }, fresh()));
    }

    // Approve this device? What the hub saw first, what it claims labelled
    // as such, the three numbers, and Deny as the default (§2.6.2, §2.6.7).
    function approval(now) {
      const d = now.device || {};
      // One whole sentence for each case: a filler phrase put into one would
      // not fit another language's grammar.
      const claim = d.browser && d.os ? M.t("device.approval.claims", { browser: d.browser, os: d.os })
        : d.browser ? M.t("device.approval.claims_browser", { browser: d.browser })
          : d.os ? M.t("device.approval.claims_os", { os: d.os })
            : M.t("device.approval.claims_nothing");
      const status2 = M.statusLine();
      const busy = (yes) => dialog.querySelectorAll("button").forEach((b) => { b.disabled = yes; });
      const send = async (verb, body, words) => {
        busy(true);
        status2.busy(words);
        try {
          await M.api.post("/auth/device-codes/" + encodeURIComponent(made.id) + "/" + verb, body);
          stop();
          ended(verb === "approve" ? M.t("device.other.approved") : M.t("device.other.denied"), verb === "approve");
        } catch (err) {
          stop();
          if (err.code === "code_invalid") ended(M.t("device.approval.wrong_number"));
          else { busy(false); status2.fail(M.t("device.not_sent"), said(err)); }
        }
      };
      const deny = h("button", { type: "button", class: "primary deny", onclick: () => send("deny", {}, M.t("device.approval.denying")) }, M.t("device.approval.deny"));
      const dialog = h("section", { class: "device-approval", role: "alertdialog", "aria-labelledby": "device-approval-title", "aria-describedby": "device-approval-warning" },
        h("h3", { id: "device-approval-title" }, M.t("device.approval.title")),
        h("dl", { class: "facts" },
          h("dt", null, M.t("device.approval.address")), h("dd", null, d.ip || "—"),
          h("dt", null, M.t("device.approval.entered")), h("dd", null, d.redeemed_at ? formatTime(d.redeemed_at) : "—"),
          h("dt", null, M.t("device.approval.claims_label")), h("dd", null, claim, d.user_agent ? h("details", null, h("summary", null, M.t("device.approval.sent")), h("code", { class: "user-agent" }, d.user_agent)) : null)),
        d.new_device ? h("p", { class: "muted" }, M.t("device.approval.first")) : null,
        h("p", { class: "flag", id: "device-approval-warning" }, h("strong", null, M.t("device.approval.warning"))),
        h("p", null, M.t("device.approval.pick")),
        h("div", { class: "match-choices", role: "group", "aria-label": M.t("device.approval.choices") },
          (now.choices || []).map((n) => h("button", { type: "button", class: "match-choice", onclick: () => send("approve", { number: n }, M.t("device.approval.approving")) }, String(n)))),
        h("div", { class: "actions" }, deny),
        status2.el);
      append(clear(stage), dialog);
      window.setTimeout(() => deny.focus(), 0);
    }
  }

  M.deviceSignIn = { loginOptions, anotherDevice, normalCode };
})(window.Maity);
