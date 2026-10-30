// Limits, a section of /admin (docs/api.md §16.5; js/instance-admin.js
// shows it to the instance admin only): the caps on what one human may
// hold — agent profiles and organisations owned — with each value's
// source (§16.2) and how many humans are at or over it. A value is a
// number (1–10000), no limit, or the default; one set by the environment
// is shown and not changed here. Only what changed is sent, and a change
// asks for the password or a code where the hub requires it (§2.8.4).
// Lowering a value deletes and pauses nothing (§16.5).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  const PATH = "/admin/settings/limits";
  const MAX = 10000;
  const FIELDS = [
    { key: "max_agents_per_human", at: "humans_at_limit", label: () => M.t("limits.agents.label"), hint: () => M.t("limits.agents.hint"),
      atWords: (n) => M.t("limits.agents.at", { count: n }) },
    { key: "max_orgs_per_human", at: "humans_at_org_limit", label: () => M.t("limits.orgs.label"), hint: () => M.t("limits.orgs.hint"),
      atWords: (n) => M.t("limits.orgs.at", { count: n }) },
  ];
  const SOURCES = { default: () => M.t("limits.source.default"), admin: () => M.t("limits.source.admin"), env: () => M.t("limits.source.env") };
  const sourceOf = (s) => (Object.hasOwn(SOURCES, s) ? SOURCES[s]() : s);
  const REASONS = { invalid: () => M.t("limits.error.invalid"), set_by_environment: () => M.t("limits.error.env"),
    read_only: () => M.t("limits.error.read_only"), extra_forbidden: () => M.t("limits.error.unknown") };

  async function section(ctx, root) {
    const status = M.statusLine();
    const body = h("div");
    const stepSlot = h("div", { class: "step-up-slot" });
    stepSlot.hidden = true;
    append(root, h("h2", null, M.t("limits.title")), h("p", { class: "muted" }, M.t("limits.intro")), status.el, stepSlot, body);
    let current = await M.api.get(PATH);

    function draw(said) {
      clear(body);
      const formStatus = M.statusLine();
      const parts = FIELDS.map((f) => {
        const v = current[f.key] || { value: null, source: "default" };
        const id = "limits-" + f.key;
        const locked = v.source === "env";
        // How the value is chosen: a number, no limit, or the default.
        const mode = h("select", { id: id + "-mode", disabled: locked ? true : null },
          h("option", { value: "number" }, M.t("limits.mode.number")),
          h("option", { value: "unlimited" }, M.t("limits.mode.unlimited")),
          h("option", { value: "default" }, M.t("limits.mode.default")));
        mode.value = v.source === "default" ? "default" : v.value === "unlimited" ? "unlimited" : "number";
        const number = h("input", { id, type: "number", min: "1", max: String(MAX), step: "1", disabled: locked ? true : null,
          "aria-describedby": id + "-hint " + id + "-error" });
        number.value = typeof v.value === "number" ? String(v.value) : "";
        const showNumber = () => { number.hidden = mode.value !== "number"; };
        mode.addEventListener("change", showNumber);
        showNumber();
        const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
        return { f, v, mode, number, error, locked, nodes: h("fieldset", { class: "limits-field" },
          h("legend", null, f.label()),
          h("label", { for: id + "-mode" }, M.t("limits.mode")), mode,
          h("label", { for: id, class: "visually-hidden" }, f.label()), number,
          h("p", { class: "hint", id: id + "-hint" }, f.hint() + " " + (locked ? M.t("limits.locked") : M.t("limits.source", { source: sourceOf(v.source) }))),
          h("p", { class: "muted limits-at" }, f.atWords(current[f.at] || 0)),
          error) };
      });
      const save = h("button", { type: "submit" }, M.t("limits.save"));
      append(body, h("form", {
        class: "inline-form admin-limits",
        onsubmit: async (e) => {
          e.preventDefault();
          const patch = {};
          let bad = null;
          parts.forEach((p) => {
            p.error.textContent = "";
            p.number.removeAttribute("aria-invalid");
            if (p.locked) return;
            let want;
            if (p.mode.value === "default") want = null;
            else if (p.mode.value === "unlimited") want = "unlimited";
            else {
              const n = Number(p.number.value);
              if (!Number.isInteger(n) || n < 1 || n > MAX) {
                p.error.textContent = M.t("limits.error.invalid");
                p.number.setAttribute("aria-invalid", "true");
                bad = bad || p.number;
                return;
              }
              want = n;
            }
            const now = p.v.source === "default" ? null : p.v.value;
            if (want !== now) patch[p.f.key] = want;
          });
          if (bad) { bad.focus(); return; }
          if (!Object.keys(patch).length) { formStatus.done(); append(formStatus.el, h("span", null, M.t("limits.unchanged"))); return; }
          save.disabled = true;
          formStatus.busy(M.t("limits.saving"));
          try {
            current = await M.stepUp.run(() => M.api.patch(PATH, patch), stepSlot, M.t("limits.step_up"));
            draw(M.t("limits.saved"));
          } catch (err) {
            save.disabled = false;
            if (err.code === "cancelled") { formStatus.done(); return; }
            const fields = err.code === "invalid" && err.details && err.details.fields;
            if (fields) {
              formStatus.done();
              parts.forEach((p) => {
                const why = fields[p.f.key];
                if (why) p.error.textContent = Object.hasOwn(REASONS, why) ? REASONS[why]() : why;
              });
              return;
            }
            formStatus.fail(M.t("limits.not_saved"), err);
          }
        },
      }, parts.map((p) => p.nodes), h("p", { class: "hint" }, M.t("limits.lowering")), save, formStatus.el));
      if (said) append(body, h("p", { class: "ok", role: "status" }, said));
    }
    draw();
    status.done();
  }

  M.adminLimits = { section };
})(window.Maity);
