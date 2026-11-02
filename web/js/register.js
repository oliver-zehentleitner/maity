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
  // What was entered so far: choosing the page's language draws the form again in it.
  // The passwords are not kept: the person types them again, nothing holds them outside the fields.
  let kept = { address: "", language: null };
  // The bar of a page without a project: the lockup and the theme.
  function bar(header) {
    append(clear(header), h("div", { class: "bar" }, M.brandTitle ? M.brandTitle() : null,
      M.api.source === "fixtures" ? h("span", { class: "source" }, M.t("header.fixtures")) : null, M.themeMenu ? M.themeMenu() : null));
  }

  async function register(main, header, next) {
    // Signed in, there is nothing to register: on to next, or the start.
    const session = await M.api.get("/auth/session").then(() => true, () => false);
    if (session) { M.route.go(next || "/all", { replace: true }); return; }
    bar(header);
    document.title = M.t("register.title") + " · Maity";
    const box = h("article", { class: "register door" });
    // The legal pages that are set, under the form (§16.7.1).
    append(clear(main), box, M.legal ? M.legal.links() : null);
    const signIn = next ? "/login?next=" + encodeURIComponent(next) : "/login";
    // Where the visitor came from (§16.7.2): the landing page's link carries
    // ?v=<variant>&c=<code>; sent as origin, the hub keeps only what it knows.
    const query = M.route.current().query;
    const v = query.get("v"), c = query.get("c");
    const origin = {};
    if (v && (v === "default" || /^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$/.test(v))) origin.variant = v;
    if (c && /^[a-z0-9-]{1,40}$/.test(c)) origin.campaign = c;
    // May this person register here? The instance's mode (§2.6.1), or an
    // address-bound invitation that admits (§3.4) when they come from one.
    let methods = null;
    let invitation = null;
    try {
      methods = await M.api.get("/auth/methods");
      // Only a token of the hub's form (§3.4) is asked about.
      const invited = next && /^\/invite\/([A-Za-z0-9_-]{22})$/.exec(next);
      if (invited) invitation = await M.api.get("/invitations/" + encodeURIComponent(invited[1])).catch(() => null);
    } catch (err) {
      append(box, h("p", { class: "send-status failed" }, M.t("register.read_failed", { reason: err.message })));
      return;
    }
    const allowed = (methods && methods.registration) || (invitation && invitation.registration === "sign_in_or_register");
    const heading = M.t("register.title");
    append(box, allowed ? M.authPages.pitch("sign_up", heading) : h("h2", null, heading));
    if (!allowed) {
      append(box, h("p", null, M.t("register.closed")),
        h("p", null, M.tn("register.closed_sign_in", { link: h("a", { href: signIn }, M.t("register.closed_sign_in.link")) })));
      return;
    }
    const address = h("input", { id: "register-address", type: "email", autocomplete: "email", required: true });
    address.value = kept.address;
    // The two languages of §6.2: this page's, and the one agents write in, which starts as the
    // first of the browser's the hub offers.
    // The agents' language stays what the person made it, whatever the page's becomes.
    let pickedLanguage = !!kept.language;
    const picker = M.languagePicker("register-language", kept.language || "en");
    kept = { address: "", language: null };
    picker.select.addEventListener("change", () => { pickedLanguage = true; });
    const site = M.interfacePicker("register-interface", M.i18n.language, false);
    if (site) site.addEventListener("change", async () => {
      kept = { address: address.value, language: pickedLanguage ? picker.select.value : null };
      await M.i18n.choose(site.value);
      M.redraw();
    });
    M.languages().then((items) => {
      if (!items || pickedLanguage) return;
      const found = M.i18n.fromBrowser(items.filter((l) => l.common).map((l) => l.tag));
      if (found) picker.set(found);
    });
    const password = h("input", { id: "register-password", type: "password", autocomplete: "new-password", required: true, minlength: String(PASSWORD_MIN) });
    const repeat = h("input", { id: "register-repeat", type: "password", autocomplete: "new-password", required: true });
    const status = M.statusLine();
    const submit = h("button", { type: "submit", class: "primary" }, M.t("register.submit"));
    const form = h("form", {
      class: "register-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        if (!address.value.trim()) { status.fail(M.t("register.not_sent"), { message: M.t("register.need_address") }); address.focus(); return; }
        if ([...password.value].length < PASSWORD_MIN) { status.fail(M.t("register.not_sent"), { message: M.t("register.short_password", { min: PASSWORD_MIN }) }); password.focus(); return; }
        if (password.value !== repeat.value) { status.fail(M.t("register.not_sent"), { message: M.t("register.passwords_differ") }); repeat.focus(); return; }
        submit.disabled = true;
        status.busy(M.t("register.sending"));
        // Only a choice of the person's goes on the account (§6.2): without one it follows the browser.
        const chosenSite = M.i18n.explicit();
        let answer;
        try {
          answer = await M.api.post("/auth/register", Object.assign({ address: address.value.trim(), password: password.value, language: picker.select.value }, chosenSite ? { interface_language: chosenSite } : {}, next ? { next } : {},
            Object.keys(origin).length ? { origin } : {}));
        } catch (err) {
          submit.disabled = false;
          status.fail(M.t("register.not_sent"), registerWords(err));
          return;
        }
        // The same answer for every address (§2.7.1): what comes next is in the mail.
        const hours = Math.round(((answer && answer.expires_in) || 86400) / 3600);
        clear(box);
        const done = h("h2", { tabindex: "-1" }, M.t("register.check_mail"));
        append(box, done,
          h("p", null, M.t("register.link_sent", { address: address.value.trim(), count: hours })),
          h("p", null, next ? M.t("register.follow_back") : M.t("register.follow")),
          h("p", { class: "muted" }, M.t("register.no_mail")));
        window.setTimeout(() => done.focus(), 0);
      },
    },
    invitation && invitation.address_bound ? h("p", { class: "hint" }, M.t("register.invited_address")) : null,
    h("label", { for: "register-address" }, M.t("register.address")), address,
    h("label", { for: "register-password" }, M.t("register.password", { min: PASSWORD_MIN })), password,
    h("label", { for: "register-repeat" }, M.t("register.repeat")), repeat,
    site ? h("label", { for: "register-interface" }, M.t("language.interface.label")) : null, site,
    h("label", { for: "register-language" }, M.t("register.language.label")), picker.search, picker.select,
    h("p", { class: "hint" }, M.t("register.language.hint")),
    submit, status.el,
    h("p", { class: "muted" }, M.tn("register.have_account", { link: h("a", { href: signIn }, M.t("register.have_account.link")) })));
    // The instance's terms (§2.7.2, from GET /auth/methods): accepted on the
    // link's page, where their version is signed; named here so nobody is
    // surprised there. A link only when it is plain https.
    const terms = methods && methods.terms;
    const termsUrl = terms && M.dom.safeUrl(terms.url);
    const termsWord = () => (termsUrl ? h("a", { href: termsUrl, target: "_blank", rel: "noopener noreferrer" }, M.t("register.terms.word")) : M.t("register.terms.word"));
    append(box, h("p", { class: "muted" }, M.t("register.explain")),
      terms ? h("p", { class: "hint register-terms" }, terms.version
        ? M.tn("register.terms_version", { terms: termsWord(), version: terms.version })
        : M.tn("register.terms", { terms: termsWord() })) : null,
      form);
  }

  function registerWords(err) {
    const d = err.details || {};
    if (d.reason === "registration_closed") return { message: M.t("register.refused.closed") };
    // Per source an hour, the instance's breaker a minute (§2.7.3): no promise of either.
    if (err.code === "rate_limited") return { message: M.t("register.refused.rate_limited") };
    if (d.fields) return { message: Object.entries(d.fields).map(([f, r]) => f + ": " + r).join("; ") };
    return err;
  }

  M.register = { page: register };
})(window.Maity);
