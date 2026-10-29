// Instance administration → Registration (docs/api.md §16.4, §2.7, §2.7.5):
// the mode, the allowlist, approval, the terms and the hourly limit, each
// with where its value comes from; what keeps registration from working
// (`missing`) beside the fields; the accounts that wait for approval, with
// Approve and Reject; and lifting a block early. A value the environment
// sets is shown, not offered (the hub refuses it, `set_by_environment`).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const SETTINGS = "/admin/settings/registration";
  const PENDING = "/admin/registrations";

  const MODES = [
    ["closed", "Closed: only invitations"],
    ["allowlist", "Allowlist: the listed domains and addresses"],
    ["open", "Open: anyone with an address"],
  ];
  const APPROVALS = [
    ["operator", "I approve each new account"],
    ["automatic", "New accounts are usable at once"],
  ];
  const SOURCES = { env: "set by the environment", admin: "set here", default: "the default", legal_pages: "from the legal pages" };
  // What keeps registration from working (§16.4 `missing`), in words.
  const MISSING = {
    mail: "Mail is not complete and enabled, so registration stays closed whatever the mode. Set it up under Mail settings.",
    allowlist: "The allowlist is empty: nobody can register, and the login page offers no registration.",
  };
  // The hub's refusals of a field, in words.
  const REASONS = {
    mail_required: "needs complete, enabled mail (Mail settings)",
    set_by_environment: "set by the environment; change it there",
    invalid: "not a valid value",
    extra_forbidden: "not known to this hub",
  };
  // A list entry the hub refuses is named `domains.<index>` or
  // `addresses.<index>` (§16.4): said as "entry N is not valid".
  const ENTRY = /^(domains|addresses)\.(\d+)$/;
  const fieldWords = (f, r) => {
    const entry = ENTRY.exec(f);
    return entry ? "entry " + (Number(entry[2]) + 1) + " is not valid" : REASONS[r] || r;
  };
  const said = (err) => {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    return { message: Object.entries(fields).map(([f, r]) => f.replace(ENTRY, "$1").replace(/_/g, " ") + ": " + fieldWords(f, r)).join("; ") };
  };
  // A list typed one per line or comma separated, trimmed, without blanks.
  const listOf = (text) => [...new Set(text.split(/[\n,]/).map((x) => x.trim().toLowerCase()).filter(Boolean))];

  async function section(ctx, root) {
    const status = M.statusLine();
    const body = h("div");
    append(root, h("h2", null, "Registration"),
      h("p", { class: "hint" }, "Who may create an account on this hub by themselves (§2.7). Invitations work in every mode."),
      status.el, body);
    let current = await M.api.get(SETTINGS);
    const canSave = await M.api.hubHas("PATCH", SETTINGS).catch(() => true);
    const stepSlot = h("div", { class: "step-up-slot" });

    function draw(words) {
      const v = (name) => (current[name] || {}).value;
      const fromEnv = (name) => (current[name] || {}).source === "env";
      const source = (name) => h("span", { class: "muted reg-source" }, " (" + (SOURCES[(current[name] || {}).source] || (current[name] || {}).source) + ")");
      const id = (k) => "reg-" + k;
      const errorOf = (k) => h("p", { class: "field-error", id: id(k) + "-error", role: "alert" });
      const errors = { mode: errorOf("mode"), domains: errorOf("domains"), addresses: errorOf("addresses"), terms: errorOf("terms"), max: errorOf("max") };

      const mode = h("select", { id: id("mode"), disabled: !canSave || fromEnv("mode") ? true : null, "aria-describedby": id("mode") + "-error" },
        MODES.map(([k, l]) => h("option", { value: k }, l)));
      mode.value = v("mode");
      const domains = h("textarea", { id: id("domains"), rows: "3", placeholder: "@example.com", disabled: !canSave || fromEnv("domains") ? true : null,
        "aria-describedby": id("domains") + "-hint " + id("domains") + "-error" });
      domains.value = (v("domains") || []).join("\n");
      const addresses = h("textarea", { id: id("addresses"), rows: "3", placeholder: "ada@example.net", disabled: !canSave || fromEnv("addresses") ? true : null,
        "aria-describedby": id("addresses") + "-error" });
      addresses.value = (v("addresses") || []).join("\n");
      const approval = h("select", { id: id("approval"), disabled: !canSave || fromEnv("approval") ? true : null },
        APPROVALS.map(([k, l]) => h("option", { value: k }, l)));
      approval.value = v("approval");
      const terms = v("terms");
      const termsOff = !canSave || fromEnv("terms") || (current.terms || {}).source === "legal_pages";
      const termsUrl = h("input", { id: id("terms-url"), type: "url", placeholder: "https://example.com/terms", disabled: termsOff ? true : null,
        "aria-describedby": id("terms") + "-error" });
      termsUrl.value = terms ? terms.url : "";
      const termsVersion = h("input", { id: id("terms-version"), placeholder: "2026-10", disabled: termsOff ? true : null,
        "aria-describedby": id("terms") + "-error" });
      termsVersion.value = terms ? terms.version : "";
      const max = h("input", { id: id("max"), type: "number", min: "1", step: "1", disabled: !canSave || fromEnv("max_new_accounts_per_hour") ? true : null,
        "aria-describedby": id("max") + "-error" });
      max.value = String(v("max_new_accounts_per_hour"));
      const save = h("button", { type: "submit", disabled: canSave ? null : true }, "Save");
      const formStatus = M.statusLine();

      const effective = current.effective_mode;
      const lines = (current.missing || []).map((m) => h("p", { class: "flag reg-missing", "data-missing": m }, MISSING[m] || "Missing: " + m));
      const form = h("form", {
        class: "project-form reg-form",
        novalidate: true,
        onsubmit: async (e) => {
          e.preventDefault();
          if (save.disabled) return;
          Object.values(errors).forEach((x) => { x.textContent = ""; });
          const patch = {};
          if (!fromEnv("mode") && mode.value !== v("mode")) patch.mode = mode.value;
          const d = listOf(domains.value), a = listOf(addresses.value);
          if (!fromEnv("domains") && JSON.stringify(d) !== JSON.stringify(v("domains") || [])) patch.domains = d;
          if (!fromEnv("addresses") && JSON.stringify(a) !== JSON.stringify(v("addresses") || [])) patch.addresses = a;
          if (!fromEnv("approval") && approval.value !== v("approval")) patch.approval = approval.value;
          if (!termsOff) {
            const url = termsUrl.value.trim(), version = termsVersion.value.trim();
            if (!!url !== !!version) { errors.terms.textContent = "The terms need both an https address and a version, or neither."; (url ? termsVersion : termsUrl).focus(); return; }
            if (url && !M.dom.safeUrl(url)) { errors.terms.textContent = "The terms' address must be plain https."; termsUrl.focus(); return; }
            if (/\s/.test(version)) { errors.terms.textContent = "The version has no spaces."; termsVersion.focus(); return; }
            const now = url ? { url, version } : null;
            if (JSON.stringify(now) !== JSON.stringify(terms || null)) patch.terms = now;
          }
          if (!fromEnv("max_new_accounts_per_hour")) {
            const n = Number(max.value);
            if (!Number.isInteger(n) || n < 1) { errors.max.textContent = "A whole number, at least 1."; max.focus(); return; }
            if (n !== v("max_new_accounts_per_hour")) patch.max_new_accounts_per_hour = n;
          }
          if (!Object.keys(patch).length) { formStatus.done(); append(formStatus.el, h("span", { class: "ok" }, "Nothing changed.")); return; }
          save.disabled = true;
          formStatus.busy("Saving…");
          try {
            // A settings change asks for the password or a code where the hub requires it (§2.8.4).
            current = await M.stepUp.run(() => M.api.patch(SETTINGS, patch), stepSlot, "Changing the registration settings");
            draw("Saved.");
            return;
          } catch (err) {
            save.disabled = false;
            if (err.code === "cancelled") { formStatus.done(); return; }
            const fields = err.code === "invalid" && err.details && err.details.fields;
            if (fields) {
              if (fields.mode) errors.mode.textContent = REASONS[fields.mode] || fields.mode;
              // A list's own refusal or one of its entries' (`domains.<index>`), at the list.
              Object.entries(fields).forEach(([f, r]) => {
                const list = f === "domains" || f === "addresses" ? f : (ENTRY.exec(f) || [])[1];
                if (list) errors[list].textContent = fieldWords(f, r);
              });
              if (fields.terms) errors.terms.textContent = REASONS[fields.terms] || fields.terms;
              if (fields.max_new_accounts_per_hour) errors.max.textContent = REASONS[fields.max_new_accounts_per_hour] || fields.max_new_accounts_per_hour;
            }
            formStatus.fail("Not saved: ", said(err));
          }
        },
      },
      h("label", { for: id("mode") }, "Mode", source("mode")), mode, errors.mode,
      h("label", { for: id("domains") }, "Domains", source("domains")), domains,
      h("p", { class: "hint", id: id("domains") + "-hint" }, "One per line, with @, like @example.com. Used only in the allowlist mode."),
      errors.domains,
      h("label", { for: id("addresses") }, "Addresses", source("addresses")), addresses, errors.addresses,
      h("label", { for: id("approval") }, "New accounts", source("approval")), approval,
      h("fieldset", { class: "reg-terms" }, h("legend", null, "Terms", source("terms")),
        h("label", { for: id("terms-url") }, "Address (https)"), termsUrl,
        h("label", { for: id("terms-version") }, "Version"), termsVersion,
        h("p", { class: "hint" }, (current.terms || {}).source === "legal_pages"
          ? "These come from the legal pages (Landing page → Terms)."
          : "Shown on the registration form and accepted when an account is completed. Leave both empty for none."),
        errors.terms),
      h("label", { for: id("max") }, "New accounts per hour at most", source("max_new_accounts_per_hour")), max, errors.max,
      save, formStatus.el, stepSlot);
      if (words) append(formStatus.el, h("span", { class: "ok" }, words));

      append(clear(body),
        h("p", { class: "reg-effective" }, "Registration now: ", h("strong", null, effective),
          effective !== v("mode") ? " (set: " + v("mode") + ")" : "", "."),
        lines,
        h("p", { class: "muted reg-counts" }, current.pending + " waiting for approval · " + current.registered_last_hour
          + " registered in the last hour · " + current.requests_dropped_last_hour + " requests dropped in the last hour"),
        form);
    }
    draw();
    status.done();
    const pendingBox = h("div", { class: "reg-pending" });
    append(root, pendingBox);
    if (await M.api.hubHas("GET", PENDING).catch(() => false)) await pendingPart(pendingBox, async () => { current = await M.api.get(SETTINGS); draw(); });
    if (await M.api.hubHas("DELETE", "/admin/registrations/blocks/{blocked}").catch(() => false)) append(root, blockPart());
  }

  // The accounts that wait for approval (§2.7.5, §16.4), oldest first.
  async function pendingPart(box, countsChanged) {
    const status = M.statusLine();
    const list = h("ul", { class: "reg-pending-list" });
    append(box, h("h3", null, "Waiting for approval"), status.el, list);
    async function load() {
      clear(list);
      let items;
      try { items = (await M.api.getAll(PENDING)).items; } catch (err) { status.fail("Could not read them: ", err); return; }
      status.done();
      if (!items.length) { append(list, h("li", { class: "muted" }, "Nobody waits for approval.")); return; }
      items.forEach((r) => append(list, row(r)));
    }
    async function decided(text) {
      await load();
      try { await countsChanged(); } catch (ignored) { /* the list said enough */ }
      append(status.el, h("span", { class: "ok" }, text));
    }
    function row(r) {
      const reasonId = "reg-reason-" + r.id;
      const reason = h("input", { id: reasonId, maxlength: "1024", autocomplete: "off", placeholder: "Why, mailed to them" });
      const rowStatus = M.statusLine();
      const approve = h("button", { type: "button", class: "primary" }, "Approve");
      const reject = h("button", { type: "submit", class: "danger" }, "Reject");
      const fail = (err) => rowStatus.fail("Not done: ", err.code === "invalid_transition"
        ? { message: "decided meanwhile (" + ((err.details || {}).from || "decided") + ")" } : err);
      approve.addEventListener("click", async () => {
        approve.disabled = true;
        rowStatus.busy("Approving…");
        try { await M.api.post(PENDING + "/" + encodeURIComponent(r.id) + "/approve", {}); await decided("@" + r.handle + " is approved."); }
        catch (err) { approve.disabled = false; fail(err); if (err.code === "invalid_transition") load(); }
      });
      return h("li", { class: "reg-pending-item", "data-registration": r.id },
        h("p", null, h("strong", null, r.display_name), " ", h("span", { class: "muted" }, "@" + r.handle + " · " + r.address)),
        h("p", { class: "muted" }, "Asked " + formatTime(r.created_at) + " · expires " + formatTime(r.expires_at)
          + (r.source_ip ? " · from " + r.source_ip : "") + (r.terms ? " · accepted terms " + (r.terms.version || r.terms) : "")),
        h("div", { class: "actions" }, approve),
        h("form", {
          class: "inline-form reg-reject",
          onsubmit: async (e) => {
            e.preventDefault();
            if (!reason.value.trim()) { rowStatus.fail("Not rejected: ", { message: "a reason is needed; it is mailed to them" }); reason.focus(); return; }
            reject.disabled = true;
            rowStatus.busy("Rejecting…");
            try { await M.api.post(PENDING + "/" + encodeURIComponent(r.id) + "/reject", { reason: reason.value.trim() }); await decided("@" + r.handle + " is rejected; the address is blocked for 30 days."); }
            catch (err) { reject.disabled = false; fail(err); if (err.code === "invalid_transition") load(); }
          },
        }, h("label", { for: reasonId }, "Reject with a reason"), reason, reject),
        rowStatus.el);
    }
    await load();
  }

  // Lifting a block early (§16.4): a rejected or expired address waits 30
  // days; the hub lists no blocks, so the address is typed.
  function blockPart() {
    const address = h("input", { id: "reg-block-address", type: "email", autocomplete: "off", placeholder: "ada@example.com" });
    const status = M.statusLine();
    const go = h("button", { type: "submit" }, "Lift the block");
    return h("form", {
      class: "inline-form reg-block",
      onsubmit: async (e) => {
        e.preventDefault();
        const a = address.value.trim();
        if (!a) { address.focus(); return; }
        go.disabled = true;
        status.busy("Lifting…");
        try {
          await M.api.del("/admin/registrations/blocks/" + encodeURIComponent(a));
          status.done();
          append(status.el, h("span", { class: "ok" }, a + " may register again (if it was blocked)."));
          address.value = "";
        } catch (err) { status.fail("Not lifted: ", err); }
        go.disabled = false;
      },
    }, h("h3", null, "Blocked addresses"),
    h("p", { class: "hint" }, "A rejected or expired registration blocks its address for 30 days. Lift it early here."),
    h("label", { for: "reg-block-address" }, "Address"), address, go, status.el);
  }

  M.adminRegistration = { section };
})(window.Maity);
