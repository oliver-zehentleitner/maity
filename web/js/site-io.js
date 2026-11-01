// The whole site as one JSON (tsk-xw8a2hd84x3a, the maintainer's choice o1): the
// landing page, the legal pages and registration as `maity-site/1`, exported and
// imported in one go in the instance admin. Each part has the shape its own
// section's import takes; a part the file leaves out stays as it is. Only the
// dashboard is involved: the parts are checked with the calls their sections use
// (the previews; registration's own check), and saved with the PATCHes they use,
// in order, the second factor asked for once. A save that stops says what is
// saved and what is not; nothing is rolled back.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const FORMAT = "maity-site/1";
  const LANDING = "/admin/settings/landing";
  const LEGAL = "/admin/settings/legal";
  const REGISTRATION = "/admin/settings/registration";
  const PAGES = ["imprint", "privacy", "terms"];
  const KEYS = ["format", "landing", "legal", "registration"];
  // The landing part takes what the landing editor imports.
  const LANDING_KEYS = ["enabled", "default_language", "pages", "footer", "variants", "campaigns"];
  const LANG = /^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$/;
  const isObject = (v) => !!v && typeof v === "object" && !Array.isArray(v);
  // Getters: the words are the catalog's when said.
  const PAGE_WORDS = { get imprint() { return M.t("site.page.imprint"); }, get privacy() { return M.t("site.page.privacy"); }, get terms() { return M.t("site.page.terms"); } };
  const PART_WORDS = { get landing() { return M.t("site.part.landing"); }, get legal() { return M.t("site.part.legal"); }, get registration() { return M.t("site.part.registration"); } };

  // Two values alike whatever the order of their keys.
  const sorted = (v) => (Array.isArray(v) ? v.map(sorted) : isObject(v) ? Object.fromEntries(Object.keys(v).sort().map((k) => [k, sorted(v[k])])) : v);
  const same = (a, b) => JSON.stringify(sorted(a)) === JSON.stringify(sorted(b));

  // What the three settings hold now, each in the shape its section exports.
  async function readNow() {
    const [landing, legal, registration] = await Promise.all([M.api.get(LANDING), M.api.get(LEGAL), M.api.get(REGISTRATION)]);
    const fixed = (k) => (registration[k] || {}).source === "env" || (k === "terms" && (registration.terms || {}).source === "legal_pages");
    return {
      landing: { enabled: !!landing.enabled, default_language: landing.default_language, pages: landing.pages || {}, footer: landing.footer || { social: [] }, variants: landing.variants || {}, campaigns: landing.campaigns || [] },
      legal: Object.fromEntries(PAGES.filter((p) => legal.pages && legal.pages[p]).map((p) => [p, { languages: legal.pages[p].languages }])),
      registration: Object.fromEntries(M.adminRegistration.FIELDS.filter((k) => registration[k] && !fixed(k)).map((k) => [k, registration[k].value])),
      fixed: M.adminRegistration.FIELDS.filter(fixed),
    };
  }
  // Registration left out when the environment sets every field: an empty part is
  // refused, and one's own file must always import again.
  const bundleOf = (now) => Object.assign({ format: FORMAT, landing: now.landing, legal: now.legal },
    Object.keys(now.registration).length ? { registration: now.registration } : {});

  // Every key a site file does not have, by its path (landing.enabeld, legal.privacy.foo).
  // One refuses the whole file: a key dropped without a word looks saved to whoever wrote it.
  function unknownPaths(data) {
    const out = Object.keys(data).filter((k) => !KEYS.includes(k));
    const under = (part, known) => (isObject(data[part]) ? Object.keys(data[part]).filter((k) => !known.includes(k)).map((k) => part + "." + k) : []);
    out.push(...under("landing", LANDING_KEYS), ...under("legal", PAGES), ...under("registration", M.adminRegistration.FIELDS));
    if (isObject(data.legal)) {
      PAGES.filter((p) => isObject(data.legal[p])).forEach((p) => Object.keys(data.legal[p]).filter((k) => k !== "languages").forEach((k) => out.push("legal." + p + "." + k)));
    }
    return out;
  }

  // The hub's refusal in a few words: the fields it names, or its message.
  const refusalWords = (err) => {
    const fields = err && err.code === "invalid" && err.details && err.details.fields;
    return fields ? Object.entries(fields).map(([f, r]) => f + ": " + r).join("; ") : (err && err.message) || String(err);
  };

  // A part's state: missing, same, changes or refused, with the words and the saves it needs.
  async function checkLanding(d, now) {
    // A value of the wrong kind refuses the part rather than falling back to the saved one without a word.
    if (!isObject(d) || !isObject(d.pages) || ("enabled" in d && typeof d.enabled !== "boolean")
      || ("default_language" in d && (typeof d.default_language !== "string" || !d.default_language)) || ("footer" in d && !isObject(d.footer))
      || ("variants" in d && !isObject(d.variants)) || ("campaigns" in d && !Array.isArray(d.campaigns))) {
      return { state: "refused", words: M.t("site.refused.landing_shape") };
    }
    const next = { enabled: "enabled" in d ? d.enabled : now.landing.enabled, default_language: "default_language" in d ? d.default_language : now.landing.default_language,
      pages: d.pages, footer: "footer" in d ? d.footer : now.landing.footer,
      variants: "variants" in d ? d.variants : now.landing.variants, campaigns: "campaigns" in d ? d.campaigns : now.landing.campaigns };
    if (same(next, now.landing)) return { state: "same" };
    try { await M.api.post(LANDING + "/preview", { default_language: next.default_language, pages: next.pages, footer: next.footer, variants: next.variants, campaigns: next.campaigns }); }
    catch (err) { return { state: "refused", words: refusalWords(err) }; }
    return { state: "changes", steps: [{ what: PART_WORDS.landing, call: () => M.api.patch(LANDING, next) }] };
  }

  async function checkLegal(d, now) {
    if (!isObject(d)) return { state: "refused", words: M.t("site.refused.legal_shape") };
    const steps = [], changed = [], words = [];
    for (const page of PAGES.filter((p) => Object.hasOwn(d, p))) {
      const langs = isObject(d[page]) ? d[page].languages : null;
      const tags = isObject(langs) ? Object.keys(langs) : [];
      if (!tags.length || tags.length > 8 || !tags.every((t) => LANG.test(t) && isObject(langs[t]) && typeof langs[t].title === "string" && typeof langs[t].markdown === "string")) {
        return { state: "refused", words: M.t("site.refused.legal_page", { page: PAGE_WORDS[page] }) };
      }
      if (now.legal[page] && same(langs, now.legal[page].languages)) continue;
      try { await M.api.post(LEGAL + "/preview?page=" + page, langs); }
      catch (err) { words.push(PAGE_WORDS[page] + ": " + refusalWords(err)); continue; }
      changed.push(PAGE_WORDS[page]);
      steps.push({ what: PAGE_WORDS[page], call: () => M.api.patch(LEGAL, { [page]: langs }) });
    }
    if (words.length) return { state: "refused", words: words.join("; ") };
    return steps.length ? { state: "changes", words: M.fmt.list(changed), steps } : { state: "same" };
  }

  function checkRegistration(d, now) {
    const refused = M.adminRegistration.check(d);
    if (refused) return { state: "refused", words: refused };
    const patch = {};
    Object.keys(d).filter((k) => !now.fixed.includes(k)).forEach((k) => { if (!same(d[k], now.registration[k])) patch[k] = d[k]; });
    const kept = Object.keys(d).filter((k) => now.fixed.includes(k));
    const note = kept.length ? M.t("site.registration.kept", { fields: M.fmt.list(kept) }) : null;
    if (!Object.keys(patch).length) return { state: "same", words: note };
    return { state: "changes", words: [M.fmt.list(Object.keys(patch)), note].filter(Boolean).join(" · "),
      steps: [{ what: PART_WORDS.registration, call: () => M.api.patch(REGISTRATION, patch) }] };
  }

  // The file as a whole: null and the parts' states, or what is wrong with it.
  async function check(data, now) {
    if (!isObject(data)) return { refused: M.t("site.refused.shape") };
    if (data.format !== FORMAT) return { refused: M.t("site.refused.format", { format: String(data.format), expected: FORMAT }) };
    const unknown = unknownPaths(data);
    if (unknown.length) return { refused: M.t("site.refused.unknown", { keys: M.fmt.list(unknown) }) };
    const parts = {
      landing: Object.hasOwn(data, "landing") ? await checkLanding(data.landing, now) : { state: "missing" },
      legal: Object.hasOwn(data, "legal") ? await checkLegal(data.legal, now) : { state: "missing" },
      registration: Object.hasOwn(data, "registration") ? checkRegistration(data.registration, now) : { state: "missing" },
    };
    return { refused: null, parts };
  }

  async function section(ctx, root) {
    const status = M.statusLine();
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    const overview = h("div", { class: "site-overview", "aria-live": "polite" });
    let now = await readNow();
    const STATE_WORDS = { get missing() { return M.t("site.state.missing"); }, get same() { return M.t("site.state.same"); },
      get changes() { return M.t("site.state.changes"); }, get refused() { return M.t("site.state.refused"); } };

    // The parts' states in a list, and one Save for every change, legal, registration, landing in that order.
    function show(parts) {
      const steps = ["legal", "registration", "landing"].flatMap((k) => parts[k].steps || []);
      const refused = Object.values(parts).some((p) => p.state === "refused");
      const save = h("button", { type: "button", class: "primary site-save", disabled: refused || !steps.length ? true : null }, M.t("site.save"));
      save.addEventListener("click", async () => {
        save.disabled = true;
        const saved = [];
        for (let i = 0; i < steps.length; i++) {
          status.busy(M.t("site.saving", { what: steps[i].what }));
          try {
            // The second factor asked for once: within its 10 minutes (§2.8.4) the next calls go through without asking.
            await M.stepUp.run(steps[i].call, stepSlot, M.t("site.step_up"));
            saved.push(steps[i].what);
          } catch (err) {
            const left = steps.slice(i).map((s) => s.what);
            status.fail(M.t("site.stopped", { what: steps[i].what }), { message: (err.code === "cancelled" ? M.t("site.cancelled") : refusalWords(err)) + " "
              + (saved.length ? M.t("site.saved_list", { parts: M.fmt.list(saved) }) : M.t("site.saved_none")) + " " + M.t("site.not_saved_list", { parts: M.fmt.list(left) }) });
            now = await readNow().catch(() => now);
            return;
          }
        }
        now = await readNow().catch(() => now);
        status.done();
        append(status.el, h("span", { class: "ok" }, M.t("site.saved_all", { parts: M.fmt.list(saved) })));
        clear(overview);
      });
      append(clear(overview), h("ul", { class: "site-parts" }, ["landing", "legal", "registration"].map((k) => h("li", { class: "site-part site-" + parts[k].state, "data-part": k },
        h("strong", null, PART_WORDS[k]), ": ", STATE_WORDS[parts[k].state], parts[k].words ? [" · ", h("span", { class: parts[k].state === "refused" ? "field-error" : "muted" }, parts[k].words)] : null))),
        refused ? h("p", { class: "field-error" }, M.t("site.refused.some")) : !steps.length ? h("p", { class: "muted" }, M.t("site.nothing")) : null,
        save);
    }

    const json = M.jsonIo.part({
      id: "site-json",
      hint: M.t("site.hint", { format: FORMAT }),
      loadLabel: M.t("site.check"),
      // Read again first: the admin page builds every section when it opens, so the
      // first read would miss an edit saved since in another section.
      body: async () => bundleOf(now = await readNow()),
      load: async (data, io) => {
        io.busy(M.t("site.checking"));
        try { now = await readNow(); } catch (err) { io.fail(M.t("site.read_failed"), err); return false; }
        const result = await check(data, now);
        if (result.refused) { io.fail(M.t("jsonio.not_loaded"), { message: result.refused }); clear(overview); return false; }
        io.done();
        show(result.parts);
        return true;
      },
    });
    const download = h("button", { type: "button", onclick: async () => {
      try { now = await readNow(); } catch (err) { status.fail(M.t("site.read_failed"), err); return; }
      status.done();
      if (M.yourData) M.yourData.save("maity-site.json", JSON.stringify(bundleOf(now), null, 2) + "\n");
    } }, M.t("site.download"));
    append(root, h("h3", null, M.t("site.title")), h("p", { class: "hint" }, M.t("site.intro")), json.el,
      h("div", { class: "actions" }, download), overview, stepSlot, status.el);
  }

  M.siteIo = { section, check, readNow, bundleOf, FORMAT };
})(window.Maity);
