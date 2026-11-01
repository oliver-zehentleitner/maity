// Two-factor sign-in on the account, /account/security (docs/api.md §2.8.1, §2.8.7): the
// state, the setup (password, QR and key, a code), the recovery codes once, new ones and
// turning it off. The same setup is the whole page of a session the hub holds in
// `enrolment_required` (§2.8.5), which reaches nothing else until it is done.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  // The hub's refusals in words; anything else as it came.
  function said(err) {
    if (err.code === "code_invalid") return { message: M.t("security.code_wrong") };
    if (err.code === "secret_key_missing") return { message: M.t("security.unavailable") };
    if (err.code === "rate_limited") return { message: M.t("security.rate_limited") };
    if (err.details && err.details.reason === "second_factor_required") return { message: M.t("security.off_refused") };
    return err;
  }

  // Shown this once (§2.8.1): the page can leave them only by "I have saved them".
  function showCodes(box, codes, saved) {
    const words = codes.join("\n") + "\n";
    const leave = h("button", { type: "button", class: "primary", onclick: saved }, M.t("security.codes.saved"));
    append(clear(box), h("div", { class: "security-codes" },
      h("h4", { tabindex: "-1", class: "security-codes-title" }, M.t("security.codes.title")),
      h("p", { class: "hint" }, M.t("security.codes.hint")),
      h("ul", { class: "security-code-list" }, codes.map((c) => h("li", null, h("code", null, c)))),
      h("div", { class: "actions" },
        h("button", { type: "button", onclick: () => M.yourData.save("maity-recovery-codes.txt", words, "text/plain") }, M.t("security.codes.download")),
        leave)));
    window.setTimeout(() => leave.focus(), 0);
  }

  // The steps of the setup, drawn in box. finished() once the codes are saved; cancelled()
  // goes back. The secret stays in this function and is never kept anywhere else.
  function setup(box, finished, cancelled) {
    const ask = h("div", { hidden: true });
    const status = M.statusLine();
    const begin = h("button", { type: "button", class: "primary" }, M.t("security.setup"));
    begin.addEventListener("click", async () => {
      begin.disabled = true;
      status.busy(M.t("security.starting"));
      let started;
      try {
        started = await M.stepUp.run(() => M.api.post("/auth/second-factor/totp", {}), ask, M.t("security.setup.what"));
      } catch (err) {
        begin.disabled = false;
        if (err.code === "cancelled") status.done();
        else status.fail(M.t("security.not_done"), said(err));
        return;
      }
      status.done();
      confirmStep(box, started, finished, cancelled);
    });
    append(clear(box), begin, ask, status.el);
  }

  function confirmStep(box, started, finished, cancelled) {
    const status = M.statusLine();
    const input = h("input", { id: "security-code", autocomplete: "one-time-code", inputmode: "numeric", spellcheck: "false", required: true });
    const submit = h("button", { type: "submit", class: "primary" }, M.t("security.confirm"));
    const form = h("form", {
      class: "security-setup",
      onsubmit: async (e) => {
        e.preventDefault();
        const code = input.value.replace(/\s+/g, "");
        if (!code) { input.focus(); return; }
        submit.disabled = true;
        status.busy(M.t("security.confirming"));
        try {
          const answer = await M.api.post("/auth/second-factor/totp/confirm", { code });
          showCodes(box, answer.recovery_codes, finished);
        } catch (err) {
          submit.disabled = false;
          status.fail(M.t("security.not_done"), said(err));
          input.value = "";
          input.focus();
        }
      },
    },
    h("p", { class: "hint" }, M.t("security.scan")),
    h("div", { class: "qr-box" }, M.qr.svg(started.otpauth_uri, 200)),
    h("p", { class: "hint" }, M.t("security.key")),
    h("p", null, h("code", { class: "security-key" }, started.secret)),
    h("label", { for: "security-code" }, M.t("security.code")), input,
    h("div", { class: "actions" }, submit,
      cancelled ? h("button", { type: "button", onclick: cancelled }, M.t("security.cancel")) : null),
    status.el);
    append(clear(box), form);
    window.setTimeout(() => input.focus(), 0);
  }

  function stateWords(state) {
    if (!state.enrolled) return state.via === "email" ? M.t("security.state.mail") : M.t("security.state.off");
    const on = M.t("security.state.on", { since: formatTime(state.enrolled_at), left: state.recovery_codes_left });
    return state.last_used_at ? on + " " + M.t("security.state.last_used", { when: formatTime(state.last_used_at) }) : on;
  }

  // The account's section; it reads the state again after each change.
  async function section() {
    const heading = h("h3", { id: "security-heading", tabindex: "-1" }, M.t("security.title"));
    const body = h("div");
    const box = h("section", { class: "security", "aria-labelledby": "security-heading" }, heading,
      h("p", { class: "muted" }, M.t("security.hint")), body);

    async function draw(note) {
      let state;
      try {
        state = await M.api.get("/auth/second-factor");
      } catch (err) {
        append(clear(body), h("p", { class: err.code === "secret_key_missing" ? "muted" : "field-error", role: "status" }, said(err).message));
        return;
      }
      const ask = h("div", { hidden: true });
      const status = M.statusLine();
      const act = async (busy, call, what, after) => {
        status.busy(busy);
        let answer;
        try {
          answer = await M.stepUp.run(call, ask, what);
        } catch (err) {
          if (err.code === "cancelled") status.done();
          else status.fail(M.t("security.not_done"), said(err));
          return;
        }
        status.done();
        after(answer);
      };
      const steps = h("div");
      const redraw = (words) => () => draw(words);
      append(clear(body), h("p", { class: "security-state" }, stateWords(state)),
        note ? h("p", { class: "ok", role: "status" }, note) : null, steps);
      if (!state.enrolled) {
        setup(steps, redraw(M.t("security.done.on")), redraw(null));
        return;
      }
      append(steps, h("div", { class: "actions" },
        h("button", { type: "button", onclick: () => act(M.t("security.starting"), () => M.api.post("/auth/second-factor/recovery-codes", {}),
          M.t("security.new_codes.what"), (a) => showCodes(steps, a.recovery_codes, redraw(M.t("security.done.codes")))) }, M.t("security.new_codes")),
        state.required ? null : h("button", { type: "button", class: "danger", onclick: () => act(M.t("security.starting"), () => M.api.del("/auth/second-factor"),
          M.t("security.off.what"), redraw(M.t("security.done.off"))) }, M.t("security.off"))),
      ask, status.el);
    }
    await draw(null);
    return { el: box, heading };
  }

  // A session in `enrolment_required` (§2.8.5): the setup is its one page.
  function enrolPage(main, done, signOut) {
    document.title = M.t("security.enrol.title") + " · Maity";
    const steps = h("div");
    append(clear(main), h("section", { class: "door security-enrol" },
      h("h2", null, M.t("security.enrol.title")),
      h("p", null, M.t("security.enrol.lead")), steps,
      h("button", { type: "button", class: "link-button", onclick: signOut }, M.t("sf.sign_out"))));
    setup(steps, done, null);
  }

  M.security = { section, enrolPage };
})(window.Maity);
