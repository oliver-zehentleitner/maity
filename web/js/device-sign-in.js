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
    if (err.code === "code_invalid") return { message: "this code does not work: it may be mistyped, used, denied or expired. Make a new one on your other device" };
    if (err.code === "rate_limited") return { message: "too many tries just now; wait a minute and try again" };
    if (err.details && err.details.reason === "method_disabled") return { message: "this hub does not offer it" };
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
    // Asked only of a hub whose machine form lists it; one without the
    // methods offers the password alone.
    M.api.hubHas("GET", "/auth/methods")
      .then((has) => (has ? M.api.get("/auth/methods") : null))
      .then((methods) => {
        if (!methods) return;
        const prefilled = codeFromAddress();
        const next = M.signInNext ? M.signInNext() : null;
        append(box,
          methods.device_code ? codeEntry(every, signedIn, prefilled) : null,
          methods.email_link ? mailLink(signedIn) : null,
          // §2.7: offered only where the instance registers.
          methods.registration ? h("p", { class: "register-link" }, "No account yet? ",
            h("a", { href: "/register" + (next ? "?next=" + encodeURIComponent(next) : "") }, "Create an account")) : null);
      }, () => {});
    return box;
  }

  // /sign-in/code#c=K7QM4XPR9D2F, the QR's URL (§2.6.2, §16.11): the code in
  // the fragment, never sent to the hub; the field filled in, sent only on
  // the human's tap. Read once, then gone from the address. In fixture mode
  // the fragment holds the route, so the code is its query there.
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
    const submit = h("button", { type: "submit", class: "primary" }, "Continue");
    const form = h("form", {
      class: "sign-in-form",
      onsubmit: (e) => {
        e.preventDefault();
        const code = normalCode(input.value);
        if (!code) { status.fail("Not sent: ", { message: "a code is twelve letters and digits, like K7QM-4XPR-9D2F" }); input.focus(); return; }
        redeem(code);
      },
    },
    h("label", { for: "device-code" }, "The code from your other device"),
    h("p", { class: "hint", id: "device-code-hint" }, "On a device where you are signed in: your profile → Sign in another device."),
    input, submit, status.el);
    const open = h("button", { type: "button", class: "link-button", "aria-expanded": "false",
      onclick: () => { showForm(); input.focus(); } }, "Have a code?");

    function showForm() {
      open.setAttribute("aria-expanded", "true");
      append(clear(panel), h("h3", { id: "sign-in-code-title" }, "Sign in with a code"), form);
    }
    async function redeem(code) {
      submit.disabled = true;
      status.busy("Sending…");
      let answer;
      try {
        const next = M.signInNext ? M.signInNext() : null;
        answer = await M.api.post("/auth/device-login", next ? { code, next } : { code });
      } catch (err) {
        submit.disabled = false;
        status.fail("Not signed in: ", said(err));
        return;
      }
      waiting(answer);
    }
    // Waiting for the other device: the match number and the time left.
    function waiting(answer) {
      const countdown = h("span", { class: "countdown" }, left(answer.expires_at));
      const note = M.statusLine();
      let expiresAt = answer.expires_at;
      const again = h("button", { type: "button", onclick: () => { stop(); input.value = ""; submit.disabled = false; status.done(); showForm(); input.focus(); } }, "Use another code");
      const view = h("div", { class: "device-waiting", role: "status" },
        h("h3", { id: "sign-in-code-title" }, "Waiting for approval on your other device"),
        h("p", null, "Pick this number there:"),
        h("p", { class: "match-number", "aria-label": "Number " + answer.match_number }, String(answer.match_number)),
        h("p", { class: "muted" }, "Expires in ", countdown, "."),
        note.el, again);
      append(clear(panel), view);
      every(1000, () => { countdown.textContent = left(expiresAt); });
      const stop = poller(every, async () => {
        let now;
        try {
          now = await M.api.get("/auth/device-login?wait=0");
        } catch (err) {
          if (err.status === 404) { stop(); note.fail("", { message: "This sign-in is no longer pending. Use another code." }); }
          return;
        }
        expiresAt = now.expires_at || expiresAt;
        if (now.status === "approved") { stop(); approved(now.account); }
        else if (now.status === "denied") { stop(); note.fail("", { message: "It was denied on your other device." }); }
        else if (now.status === "expired") { stop(); note.fail("", { message: "The code expired. Make a new one on your other device." }); }
      });
    }
    // Approved: only now the account (§2.6.2), then this browser's session.
    async function approved(account) {
      const status2 = M.statusLine();
      append(clear(panel), h("div", { class: "device-approved", role: "status" },
        h("h3", { id: "sign-in-code-title" }, "Approved"),
        account ? h("p", { class: "device-account" }, M.avatar(Object.assign({ id: account.handle }, account), 32), " Signing you in as ", h("strong", null, account.display_name), " @" + account.handle) : null,
        status2.el));
      status2.busy("Signing in…");
      try {
        const done = await M.api.post("/auth/device-login/complete", {});
        goNext(done.next);
        signedIn();
      } catch (err) {
        status2.fail("Not signed in: ", said(err));
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
        status.busy("Sending…");
        try {
          const next = M.signInNext ? M.signInNext() : null;
          await M.api.post("/auth/email-link", next ? { address: address.value.trim(), next } : { address: address.value.trim() });
          status.done();
          codeForm();
        } catch (err) {
          status.fail("Not sent: ", said(err));
        }
      },
    },
    h("h3", { id: "sign-in-mail-title" }, "Sign in by mail"),
    h("label", { for: "sign-in-address" }, "Your address"), address,
    h("button", { type: "submit" }, "Email me a sign-in link"), status.el);
    function codeForm() {
      const code = h("input", { id: "sign-in-mail-code", inputmode: "numeric", autocomplete: "one-time-code", "aria-describedby": "sign-in-mail-sent" });
      const status2 = M.statusLine();
      append(clear(panel), h("form", {
        class: "sign-in-form",
        onsubmit: async (e) => {
          e.preventDefault();
          const digits = code.value.replace(/\s/g, "");
          if (!/^\d{6}$/.test(digits)) { status2.fail("Not sent: ", { message: "the code in the mail has six digits" }); code.focus(); return; }
          status2.busy("Signing in…");
          try {
            const done = await M.api.post("/auth/email-code", { code: digits });
            goNext(done.next);
            signedIn();
          } catch (err) {
            status2.fail("Not signed in: ", err.code === "code_invalid" ? { message: "that code does not match" } : said(err));
          }
        },
      },
      h("h3", { id: "sign-in-mail-title" }, "Check your mail"),
      h("p", { id: "sign-in-mail-sent", role: "status" }, "If this address belongs to an account, a link is on its way. Open it here, or enter the code from the mail."),
      h("label", { for: "sign-in-mail-code" }, "The six-digit code"), code,
      h("button", { type: "submit", class: "primary" }, "Sign in"), status2.el));
      code.focus();
    }
    const open = h("button", { type: "button", class: "link-button", "aria-expanded": "false",
      onclick: () => { append(clear(panel), ask); address.focus(); } }, "Email me a sign-in link");
    append(panel, open);
    return panel;
  }

  // ---- the signed-in device: /account/sign-in-device ----------------------

  async function anotherDevice(ctx, root) {
    const heading = h("h2", { tabindex: "-1" }, "Sign in another device");
    const stage = h("div", { class: "device-stage" });
    append(root, heading,
      h("p", { class: "muted" }, "On the other device, open the sign-in page and choose Have a code?, or scan the QR code. "
        + "You approve it here, after it entered the code."),
      stage);
    window.setTimeout(() => heading.focus(), 0);
    await start(ctx, stage);
  }

  // The QR of the code's URL; the code and Cancel stand without it.
  function qrOf(url) {
    try {
      return h("div", { class: "qr-box" }, M.qr.svg(url, 200));
    } catch (err) {
      return h("p", { class: "muted" }, "No QR code for this hub's address: enter the code on the other device instead.");
    }
  }

  async function start(ctx, stage) {
    const status = M.statusLine();
    append(clear(stage), status.el);
    status.busy("Making a code…");
    let made;
    try {
      made = await M.api.post("/auth/device-codes", {});
    } catch (err) {
      if (await M.api.missingRoute(err, "POST", "/auth/device-codes")) { append(clear(stage), M.dom.notOnHub("This hub has no sign-in by code yet.")); return; }
      if (err.details && err.details.reason === "method_disabled") { append(clear(stage), M.dom.notOnHub("This hub does not offer sign-in by code.")); return; }
      status.fail("No code: ", said(err));
      return;
    }
    const code = normalCode(made.code) || made.code;
    const countdown = h("span", { class: "countdown" }, left(made.expires_at));
    const fresh = () => h("button", { type: "button", onclick: () => { stop(); start(ctx, stage); } }, "New code");
    const cancel = h("button", { type: "button", onclick: async () => {
      stop();
      try { await M.api.del("/auth/device-codes/" + encodeURIComponent(made.id)); } catch (err) { /* it ends with its expiry anyway */ }
      ended("Cancelled.");
    } }, "Cancel");
    const view = h("div", { class: "device-code" },
      h("p", { class: "device-code-text", "aria-label": "Code " + [...code.replace("-", "")].join(" ") }, grouped(code.replace("-", ""))),
      qrOf(made.url),
      h("p", { class: "muted" }, "Expires in ", countdown, ". Waiting for the other device…"),
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
        if (err.status === 404) { stop(); ended("This code is gone (its session ended)."); }
        return;
      }
      expiresAt = now.expires_at || expiresAt;
      if (now.status === "redeemed" && shown !== "redeemed") { shown = "redeemed"; approval(now); }
      else if (now.status === "approved" || now.status === "used") { stop(); ended(now.status === "used" ? "The other device is signed in." : "Approved: the other device is signing in.", true); }
      else if (now.status === "denied") { stop(); ended("Denied. The code is dead."); }
      else if (now.status === "expired") { stop(); ended("The code expired."); }
    });

    function ended(words, good) {
      append(clear(stage), h("p", { class: good ? "ok" : "muted", role: "status" }, words), good ? null : h("div", { class: "actions" }, fresh()));
    }

    // Approve this device? What the hub saw first, what it claims labelled
    // as such, the three numbers, and Deny as the default (§2.6.2, §2.6.7).
    function approval(now) {
      const d = now.device || {};
      const claim = d.browser || d.os
        ? "Says it is " + (d.browser || "an unknown browser") + " on " + (d.os || "an unknown system")
        : "Says nothing we could read about its browser";
      const status2 = M.statusLine();
      const busy = (yes) => dialog.querySelectorAll("button").forEach((b) => { b.disabled = yes; });
      const send = async (verb, body, words) => {
        busy(true);
        status2.busy(words);
        try {
          await M.api.post("/auth/device-codes/" + encodeURIComponent(made.id) + "/" + verb, body);
          stop();
          ended(verb === "approve" ? "Approved: the other device is signing in." : "Denied. The code is dead.", verb === "approve");
        } catch (err) {
          stop();
          if (err.code === "code_invalid") ended("That was not the number it shows, so the code is denied. If the device is yours, make a new code.");
          else { busy(false); status2.fail("Not sent: ", said(err)); }
        }
      };
      const deny = h("button", { type: "button", class: "primary deny", onclick: () => send("deny", {}, "Denying…") }, "Deny");
      const dialog = h("section", { class: "device-approval", role: "alertdialog", "aria-labelledby": "device-approval-title", "aria-describedby": "device-approval-warning" },
        h("h3", { id: "device-approval-title" }, "Approve this device?"),
        h("dl", { class: "facts" },
          h("dt", null, "Address"), h("dd", null, d.ip || "—"),
          h("dt", null, "Entered the code"), h("dd", null, d.redeemed_at ? formatTime(d.redeemed_at) : "—"),
          h("dt", null, "Claims"), h("dd", null, claim, d.user_agent ? h("details", null, h("summary", null, "What it sent"), h("code", { class: "user-agent" }, d.user_agent)) : null)),
        d.new_device ? h("p", { class: "muted" }, "First sign-in from this browser.") : null,
        h("p", { class: "flag", id: "device-approval-warning" }, h("strong", null, "Only approve a device you are holding now.")),
        h("p", null, "Pick the number it shows. None of these, or no number on it? Deny."),
        h("div", { class: "match-choices", role: "group", "aria-label": "The number the device shows" },
          (now.choices || []).map((n) => h("button", { type: "button", class: "match-choice", onclick: () => send("approve", { number: n }, "Approving…") }, String(n)))),
        h("div", { class: "actions" }, deny),
        status2.el);
      append(clear(stage), dialog);
      window.setTimeout(() => deny.focus(), 0);
    }
  }

  M.deviceSignIn = { loginOptions, anotherDevice, normalCode };
})(window.Maity);
