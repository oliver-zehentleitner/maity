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
  // How long a rejected or expired registration blocks its address (§16.4).
  const BLOCK_DAYS = 30;

  // Getters: the words are the catalog's when shown.
  const MODES = ["closed", "allowlist", "open"];
  const MODE_LABELS = {
    get closed() { return M.t("reg.mode.closed"); },
    get allowlist() { return M.t("reg.mode.allowlist"); },
    get open() { return M.t("reg.mode.open"); },
  };
  const APPROVALS = ["operator", "automatic"];
  const APPROVAL_LABELS = {
    get operator() { return M.t("reg.approval.operator"); },
    get automatic() { return M.t("reg.approval.automatic"); },
  };
  const SOURCES = {
    get env() { return M.t("reg.source.env"); },
    get admin() { return M.t("reg.source.admin"); },
    get default() { return M.t("reg.source.default"); },
    get legal_pages() { return M.t("reg.source.legal_pages"); },
  };
  // What keeps registration from working (§16.4 `missing`), in words.
  const MISSING = {
    get mail() { return M.t("reg.missing.mail"); },
    get allowlist() { return M.t("reg.missing.allowlist"); },
  };
  // The hub's refusals of a field, in words.
  const REASONS = {
    get mail_required() { return M.t("reg.refused.mail_required"); },
    get set_by_environment() { return M.t("reg.refused.set_by_environment"); },
    get invalid() { return M.t("reg.refused.invalid"); },
    get extra_forbidden() { return M.t("reg.refused.extra_forbidden"); },
  };
  const reason = (r) => (Object.hasOwn(REASONS, r) ? REASONS[r] : r);
  // A list entry the hub refuses is named `domains.<index>` or
  // `addresses.<index>` (§16.4): said as "entry N is not valid".
  const ENTRY = /^(domains|addresses)\.(\d+)$/;
  const fieldWords = (f, r) => {
    const entry = ENTRY.exec(f);
    return entry ? M.t("reg.refused.entry", { n: String(Number(entry[2]) + 1) }) : reason(r);
  };
  const said = (err) => {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (!fields) return err;
    return { message: Object.entries(fields).map(([f, r]) => M.t("reg.refused.field", { field: f.replace(ENTRY, "$1").replace(/_/g, " "), why: fieldWords(f, r) })).join("; ") };
  };
  // A list typed one per line or comma separated, trimmed, without blanks.
  const listOf = (text) => [...new Set(text.split(/[\n,]/).map((x) => x.trim().toLowerCase()).filter(Boolean))];

  async function section(ctx, root) {
    const status = M.statusLine();
    const body = h("div");
    append(root, h("h2", null, M.t("reg.title")),
      h("p", { class: "hint" }, M.t("reg.intro")),
      status.el, body);
    let current = await M.api.get(SETTINGS);
    const stepSlot = h("div", { class: "step-up-slot" });
    // What the hub does now, what is missing and the counts: redrawn on their
    // own after a decision, so the form keeps what is typed and not saved.
    const summary = h("div", { class: "reg-summary" });
    function drawSummary() {
      const set = (current.mode || {}).value, effective = current.effective_mode;
      append(clear(summary),
        h("p", { class: "reg-effective" }, effective !== set
          ? M.tn("reg.effective_set", { mode: h("strong", null, effective), set })
          : M.tn("reg.effective", { mode: h("strong", null, effective) })),
        (current.missing || []).map((m) => h("p", { class: "flag reg-missing", "data-missing": m }, Object.hasOwn(MISSING, m) ? MISSING[m] : M.t("reg.missing.other", { what: m }))),
        // Facts with a middle dot between them, each one whole.
        h("p", { class: "muted reg-counts" }, [M.t("reg.count.pending", { count: current.pending }), M.t("reg.count.registered", { count: current.registered_last_hour }),
          M.t("reg.count.dropped", { count: current.requests_dropped_last_hour })].join(" · ")));
    }

    // Values loaded from JSON and not saved yet: shown in the form, which
    // compares them with the stored ones on Save as it does typed ones.
    let loaded = {};
    // The form's values as last drawn (for the export).
    let formBody = () => ({});
    function draw(words) {
      const v = (name) => (current[name] || {}).value;
      const shown = (name) => (Object.hasOwn(loaded, name) ? loaded[name] : v(name));
      const fromEnv = (name) => (current[name] || {}).source === "env";
      const source = (name) => {
        const from = (current[name] || {}).source;
        return h("span", { class: "muted reg-source" }, " " + M.t("reg.source.said", { source: Object.hasOwn(SOURCES, from) ? SOURCES[from] : from }));
      };
      const id = (k) => "reg-" + k;
      const errorOf = (k) => h("p", { class: "field-error", id: id(k) + "-error", role: "alert" });
      const errors = { mode: errorOf("mode"), domains: errorOf("domains"), addresses: errorOf("addresses"), terms: errorOf("terms"), max: errorOf("max") };

      const mode = h("select", { id: id("mode"), disabled: fromEnv("mode") ? true : null, "aria-describedby": id("mode") + "-error" },
        MODES.map((k) => h("option", { value: k }, MODE_LABELS[k])));
      mode.value = shown("mode");
      const domains = h("textarea", { id: id("domains"), rows: "3", placeholder: "@example.com", disabled: fromEnv("domains") ? true : null,
        "aria-describedby": id("domains") + "-hint " + id("domains") + "-error" });
      domains.value = (shown("domains") || []).join("\n");
      const addresses = h("textarea", { id: id("addresses"), rows: "3", placeholder: "ada@example.net", disabled: fromEnv("addresses") ? true : null,
        "aria-describedby": id("addresses") + "-error" });
      addresses.value = (shown("addresses") || []).join("\n");
      const approval = h("select", { id: id("approval"), disabled: fromEnv("approval") ? true : null },
        APPROVALS.map((k) => h("option", { value: k }, APPROVAL_LABELS[k])));
      approval.value = shown("approval");
      const terms = v("terms");
      const termsShown = shown("terms");
      const termsOff = fromEnv("terms") || (current.terms || {}).source === "legal_pages";
      const termsUrl = h("input", { id: id("terms-url"), type: "url", placeholder: "https://example.com/terms", disabled: termsOff ? true : null,
        "aria-describedby": id("terms") + "-error" });
      termsUrl.value = termsShown ? termsShown.url : "";
      const termsVersion = h("input", { id: id("terms-version"), placeholder: "2026-10", disabled: termsOff ? true : null,
        "aria-describedby": id("terms") + "-error" });
      termsVersion.value = termsShown ? termsShown.version : "";
      const max = h("input", { id: id("max"), type: "number", min: "1", step: "1", disabled: fromEnv("max_new_accounts_per_hour") ? true : null,
        "aria-describedby": id("max") + "-error" });
      max.value = String(shown("max_new_accounts_per_hour"));
      // What a PATCH would carry, from the form; a value the environment sets is left out.
      formBody = () => {
        const out = {};
        const put = (name, value) => { if (!fromEnv(name)) out[name] = value; };
        put("mode", mode.value);
        put("domains", listOf(domains.value));
        put("addresses", listOf(addresses.value));
        put("approval", approval.value);
        if (!termsOff) out.terms = termsUrl.value.trim() ? { url: termsUrl.value.trim(), version: termsVersion.value.trim() } : null;
        put("max_new_accounts_per_hour", Number(max.value));
        return out;
      };
      const save = h("button", { type: "submit" }, M.t("reg.save"));
      const formStatus = M.statusLine();

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
            if (!!url !== !!version) { errors.terms.textContent = M.t("reg.terms.both"); (url ? termsVersion : termsUrl).focus(); return; }
            if (url && !M.dom.safeUrl(url)) { errors.terms.textContent = M.t("reg.terms.https"); termsUrl.focus(); return; }
            if (/\s/.test(version)) { errors.terms.textContent = M.t("reg.terms.no_spaces"); termsVersion.focus(); return; }
            const now = url ? { url, version } : null;
            if (JSON.stringify(now) !== JSON.stringify(terms || null)) patch.terms = now;
          }
          if (!fromEnv("max_new_accounts_per_hour")) {
            const n = Number(max.value);
            if (!Number.isInteger(n) || n < 1) { errors.max.textContent = M.t("reg.max.invalid"); max.focus(); return; }
            if (n !== v("max_new_accounts_per_hour")) patch.max_new_accounts_per_hour = n;
          }
          if (!Object.keys(patch).length) { formStatus.done(); append(formStatus.el, h("span", { class: "ok" }, M.t("reg.unchanged"))); return; }
          save.disabled = true;
          formStatus.busy(M.t("reg.saving"));
          try {
            // A settings change asks for the password or a code where the hub requires it (§2.8.4).
            current = await M.stepUp.run(() => M.api.patch(SETTINGS, patch), stepSlot, M.t("reg.step_up"));
            loaded = {};
            draw(M.t("reg.saved"));
            return;
          } catch (err) {
            save.disabled = false;
            if (err.code === "cancelled") { formStatus.done(); return; }
            const fields = err.code === "invalid" && err.details && err.details.fields;
            if (fields) {
              if (fields.mode) errors.mode.textContent = reason(fields.mode);
              // A list's own refusal or one of its entries' (`domains.<index>`), at the list.
              Object.entries(fields).forEach(([f, r]) => {
                const list = f === "domains" || f === "addresses" ? f : (ENTRY.exec(f) || [])[1];
                if (list) errors[list].textContent = fieldWords(f, r);
              });
              if (fields.terms) errors.terms.textContent = reason(fields.terms);
              if (fields.max_new_accounts_per_hour) errors.max.textContent = reason(fields.max_new_accounts_per_hour);
            }
            formStatus.fail(M.t("reg.not_saved"), said(err));
          }
        },
      },
      h("label", { for: id("mode") }, M.t("reg.field.mode"), source("mode")), mode, errors.mode,
      h("label", { for: id("domains") }, M.t("reg.field.domains"), source("domains")), domains,
      h("p", { class: "hint", id: id("domains") + "-hint" }, M.t("reg.field.domains_hint")),
      errors.domains,
      h("label", { for: id("addresses") }, M.t("reg.field.addresses"), source("addresses")), addresses, errors.addresses,
      h("label", { for: id("approval") }, M.t("reg.field.approval"), source("approval")), approval,
      h("fieldset", { class: "reg-terms" }, h("legend", null, M.t("reg.field.terms"), source("terms")),
        h("label", { for: id("terms-url") }, M.t("reg.terms.url")), termsUrl,
        h("label", { for: id("terms-version") }, M.t("reg.terms.version")), termsVersion,
        h("p", { class: "hint" }, (current.terms || {}).source === "legal_pages" ? M.t("reg.terms.from_legal") : M.t("reg.terms.hint")),
        errors.terms),
      h("label", { for: id("max") }, M.t("reg.field.max"), source("max_new_accounts_per_hour")), max, errors.max,
      save, formStatus.el, stepSlot);
      if (words) append(formStatus.el, h("span", { class: "ok" }, words));

      drawSummary();
      append(clear(body), summary, form);
    }
    draw();
    // Import and export of the setting as the PATCH body (§16.4). The hub has no
    // dry check here: a loaded value is checked when it is saved.
    const FIELDS = ["mode", "domains", "addresses", "approval", "terms", "max_new_accounts_per_hour"];
    append(root, M.jsonIo.part({
      id: "reg-json",
      hint: M.t("jsonio.reg.hint"),
      body: () => formBody(),
      load: async (data, io) => {
        const keys = M.jsonIo.isObject(data) ? Object.keys(data) : [];
        const unknown = keys.filter((k) => !FIELDS.includes(k));
        if (!keys.length || unknown.length) {
          io.fail(M.t("jsonio.not_loaded"), { message: unknown.length ? M.t("jsonio.reg.unknown", { fields: M.fmt.list(unknown) }) : M.t("jsonio.reg.shape") });
          return false;
        }
        // A value the environment sets stays as it is (the hub refuses it, set_by_environment).
        const fixed = keys.filter((k) => (current[k] || {}).source === "env" || (k === "terms" && (current.terms || {}).source === "legal_pages"));
        if (!window.confirm(fixed.length ? M.t("jsonio.reg.confirm_fixed", { fields: M.fmt.list(fixed) }) : M.t("jsonio.reg.confirm"))) return false;
        loaded = {};
        keys.filter((k) => !fixed.includes(k)).forEach((k) => { loaded[k] = data[k]; });
        draw();
        io.done();
        append(io.el, h("span", { class: "ok" }, M.t("jsonio.reg.loaded")));
        return true;
      },
    }).el);
    status.done();
    const pendingBox = h("div", { class: "reg-pending" });
    append(root, pendingBox);
    await pendingPart(pendingBox, async () => { current = await M.api.get(SETTINGS); drawSummary(); });
    append(root, blockPart());
  }

  // The accounts that wait for approval (§2.7.5, §16.4), oldest first.
  async function pendingPart(box, countsChanged) {
    const status = M.statusLine();
    const list = h("ul", { class: "reg-pending-list" });
    append(box, h("h3", null, M.t("reg.pending.title")), status.el, list);
    async function load() {
      clear(list);
      let items;
      try { items = (await M.api.getAll(PENDING)).items; } catch (err) { status.fail(M.t("reg.pending.read_failed"), err); return; }
      status.done();
      if (!items.length) { append(list, h("li", { class: "muted" }, M.t("reg.pending.none"))); return; }
      items.forEach((r) => append(list, row(r)));
    }
    async function decided(text) {
      await load();
      try { await countsChanged(); } catch (ignored) { /* the list said enough */ }
      append(status.el, h("span", { class: "ok" }, text));
    }
    function row(r) {
      const reasonId = "reg-reason-" + r.id;
      const why = h("input", { id: reasonId, maxlength: "1024", autocomplete: "off", placeholder: M.t("reg.pending.why_placeholder") });
      const rowStatus = M.statusLine();
      const approve = h("button", { type: "button", class: "primary" }, M.t("reg.pending.approve"));
      const reject = h("button", { type: "submit", class: "danger" }, M.t("reg.pending.reject"));
      const fail = (err) => rowStatus.fail(M.t("reg.pending.not_done"), err.code === "invalid_transition"
        ? { message: (err.details || {}).from ? M.t("reg.pending.decided", { from: err.details.from }) : M.t("reg.pending.decided_unknown") } : err);
      approve.addEventListener("click", async () => {
        approve.disabled = true;
        rowStatus.busy(M.t("reg.pending.approving"));
        try { await M.api.post(PENDING + "/" + encodeURIComponent(r.id) + "/approve", {}); await decided(M.t("reg.pending.approved", { handle: r.handle })); }
        catch (err) { approve.disabled = false; fail(err); if (err.code === "invalid_transition") load(); }
      });
      return h("li", { class: "reg-pending-item", "data-registration": r.id },
        h("p", null, h("strong", null, r.display_name), " ", h("span", { class: "muted" }, "@" + r.handle + " · " + r.address)),
        // Facts with a middle dot between them, each one whole.
        h("p", { class: "muted" }, [M.t("reg.pending.asked", { time: formatTime(r.created_at) }), M.t("reg.pending.expires", { time: formatTime(r.expires_at) }),
          r.source_ip ? M.t("reg.pending.from", { ip: r.source_ip }) : null,
          r.terms ? M.t("reg.pending.terms", { version: String(r.terms.version || r.terms) }) : null].filter(Boolean).join(" · ")),
        h("div", { class: "actions" }, approve),
        h("form", {
          class: "inline-form reg-reject",
          onsubmit: async (e) => {
            e.preventDefault();
            if (!why.value.trim()) { rowStatus.fail(M.t("reg.pending.not_rejected"), { message: M.t("reg.pending.reason_needed") }); why.focus(); return; }
            reject.disabled = true;
            rowStatus.busy(M.t("reg.pending.rejecting"));
            try {
              await M.api.post(PENDING + "/" + encodeURIComponent(r.id) + "/reject", { reason: why.value.trim() });
              await decided(M.t("reg.pending.rejected", { handle: r.handle, count: BLOCK_DAYS }));
            } catch (err) { reject.disabled = false; fail(err); if (err.code === "invalid_transition") load(); }
          },
        }, h("label", { for: reasonId }, M.t("reg.pending.reject_label")), why, reject),
        rowStatus.el);
    }
    await load();
  }

  // Lifting a block early (§16.4): a rejected or expired address waits 30
  // days; the hub lists no blocks, so the address is typed.
  function blockPart() {
    const address = h("input", { id: "reg-block-address", type: "email", autocomplete: "off", placeholder: "ada@example.com" });
    const status = M.statusLine();
    const go = h("button", { type: "submit" }, M.t("reg.block.lift"));
    return h("form", {
      class: "inline-form reg-block",
      onsubmit: async (e) => {
        e.preventDefault();
        const a = address.value.trim();
        if (!a) { address.focus(); return; }
        go.disabled = true;
        status.busy(M.t("reg.block.lifting"));
        try {
          await M.api.del("/admin/registrations/blocks/" + encodeURIComponent(a));
          status.done();
          append(status.el, h("span", { class: "ok" }, M.t("reg.block.lifted", { address: a })));
          address.value = "";
        } catch (err) { status.fail(M.t("reg.block.failed"), err); }
        go.disabled = false;
      },
    }, h("h3", null, M.t("reg.block.title")),
    h("p", { class: "hint" }, M.t("reg.block.hint", { count: BLOCK_DAYS })),
    h("label", { for: "reg-block-address" }, M.t("reg.block.address")), address, go, status.el);
  }

  M.adminRegistration = { section };
})(window.Maity);
