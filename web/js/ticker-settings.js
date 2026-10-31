// The change ticker's project settings and the forge webhook, in Project
// settings (docs/api.md §6.1, §17.3, §17.4; the maintainer's wish,
// tsk-a3cj2canahy3): whether the hub announces merges, decisions, releases
// and deploys, which files are the contract and who implements which of
// their sections, and the secret a forge signs its deliveries with. A
// human with project:admin changes them; every member reads the ticker
// setting. One's own follow and mute are in the Ticker view (§17.8).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatTime } = M.dom;

  const FILES_MAX = 10;
  const KEYS_MAX = 200;
  const TOKENS_MAX = 20;
  const TOKEN = /^(area:\S+|member:[A-Za-z0-9_-]+|role:[a-z_]+|trust:[a-z_]+)$/;

  // "8: area:hub/ area:web/" per line, as the mapping is written to the hub.
  const linesOf = (map) => Object.keys(map || {}).map((k) => k + ": " + map[k].join(" ")).join("\n");
  function parseImplementers(text) {
    const map = {};
    const errors = [];
    String(text || "").split("\n").map((l) => l.trim()).filter(Boolean).forEach((line, i) => {
      const m = /^(\*|\d+(?:\.\d+)*)\s*:\s*(.*)$/.exec(line);
      if (!m) { errors.push(M.t("tickerset.err.shape", { line: i + 1 })); return; }
      const tokens = m[2].split(/\s+/).filter(Boolean);
      const bad = tokens.filter((t) => !TOKEN.test(t));
      if (bad.length) errors.push(M.t("tickerset.err.token", { line: i + 1, tokens: bad.join(", "), count: bad.length }));
      if (tokens.length > TOKENS_MAX) errors.push(M.t("tickerset.err.tokens_max", { line: i + 1, count: TOKENS_MAX }));
      map[m[1]] = tokens;
    });
    if (Object.keys(map).length > KEYS_MAX) errors.push(M.t("tickerset.err.keys_max", { count: KEYS_MAX }));
    return { map, errors };
  }

  // An area contains a path as the hub reads it (hub/ticker.py contains, §6.2):
  // `/` every path; `hub` and `hub/` the same directory; `hub` not `hubris`.
  function contains(area, path) {
    if (area === "/") return true;
    const bare = area.replace(/\/+$/, "");
    return path === bare || path.replace(/\/+$/, "") === bare || path.startsWith(bare + "/");
  }

  // A token that names nobody now (§17.3: the view shows it as unresolved).
  function unresolved(ctx, token) {
    const [kind, value] = [token.slice(0, token.indexOf(":")), token.slice(token.indexOf(":") + 1)];
    const members = ctx.members || [];
    if (kind === "member") return !members.some((m) => m.id === value);
    // A role names its members, a project role's base included (§2.3).
    if (kind === "role") return !members.some((m) => M.trust.roleIs(m, value));
    if (kind === "trust") return !M.trust.TRUSTS.includes(value) || !members.some((m) => m.trust === value);
    if (kind === "area") return !members.some((m) => (m.areas || []).some((a) => contains(a, value)));
    return true;
  }

  function tickerForm(ctx, save) {
    const t = (ctx.project.settings || {}).ticker || {};
    const mayEdit = ctx.me.kind === "human" && ctx.canAdmin;
    const enabled = h("input", { id: "ticker-enabled", type: "checkbox", disabled: mayEdit ? null : true });
    enabled.checked = !!t.enabled;
    const files = h("textarea", { id: "ticker-files", rows: "2", spellcheck: "false", disabled: mayEdit ? null : true, placeholder: "docs/api.md" });
    files.value = (t.contract_files || []).join("\n");
    const impl = h("textarea", { id: "ticker-implementers", rows: "4", spellcheck: "false", disabled: mayEdit ? null : true,
      placeholder: "8: area:hub/ area:web/\n*: area:hub/", "aria-describedby": "ticker-implementers-hint ticker-unresolved" });
    impl.value = linesOf(t.contract_implementers);
    const unresolvedBox = h("p", { class: "flag", id: "ticker-unresolved", hidden: true });
    const showUnresolved = () => {
      const { map } = parseImplementers(impl.value);
      const lost = [...new Set([].concat(...Object.values(map)).filter((tok) => TOKEN.test(tok) && unresolved(ctx, tok)))];
      unresolvedBox.hidden = !lost.length;
      unresolvedBox.textContent = lost.length ? M.t("tickerset.unresolved", { tokens: lost.join(", ") }) : "";
    };
    impl.addEventListener("input", showUnresolved);
    showUnresolved();
    const status = M.statusLine();
    const form = h("form", {
      class: "inline-form ticker-settings",
      onsubmit: (e) => {
        e.preventDefault();
        if (!mayEdit) return;
        const paths = files.value.split("\n").map((l) => l.trim()).filter(Boolean);
        const { map, errors } = parseImplementers(impl.value);
        if (paths.length > FILES_MAX) errors.push(M.t("tickerset.err.files_max", { count: FILES_MAX }));
        if (errors.length) { status.fail(M.t("tickerset.not_saved"), { message: errors.join("; ") }); return; }
        // Sent whole (§6.1): what the form leaves out is gone.
        save({ settings: { ticker: { enabled: enabled.checked, contract_files: paths, contract_implementers: map } } }, M.t("tickerset.saved_label"));
      },
    },
    h("h2", { class: "panel-title" }, M.t("tickerset.title")),
    h("label", { class: "check", for: "ticker-enabled" }, enabled, " ", M.t("tickerset.enabled")),
    h("p", { class: "hint" }, M.tn("tickerset.enabled.hint", { ticker: h("a", { href: ctx.link("ticker") }, M.t("tickerset.enabled.hint.link")) })),
    h("label", { for: "ticker-files" }, M.t("tickerset.files")), files,
    h("label", { for: "ticker-implementers" }, M.t("tickerset.implementers")), impl,
    h("p", { class: "hint", id: "ticker-implementers-hint" }, M.t("tickerset.implementers.hint")),
    unresolvedBox,
    mayEdit ? h("button", { type: "submit" }, M.t("tickerset.save")) : h("p", { class: "muted" }, M.t("tickerset.read_only")),
    status.el);
    return form;
  }

  // The forge's webhook (§17.4): set or not, its last delivery; a secret
  // made or rotated is shown once with the address to enter at the forge.
  function webhookPanel(ctx) {
    const box = h("section", { class: "panel webhook", "aria-labelledby": "webhook-title" });
    const body = h("div");
    const status = M.statusLine();
    append(box, h("h2", { class: "panel-title", id: "webhook-title" }, M.t("webhook.title")),
      h("p", { class: "hint" }, M.t("webhook.hint")),
      body, status.el);
    const path = ctx.base + "/forge/webhook";
    let busy = false;
    async function act(fn) {
      if (busy) return;
      busy = true;
      try { await fn(); } finally { busy = false; }
    }
    // A secret just made, from the POST's own answer: shown whatever the read
    // after it does, since it is shown only now and a rotation already
    // ended the old one. Kept in the page only, never stored.
    function secretBlock(shown) {
      const copy = h("button", { type: "button", class: "small" }, M.t("webhook.copy"));
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(shown.secret); copy.textContent = M.t("webhook.copied"); } catch (err) { copy.textContent = M.t("webhook.copy_failed"); }
      });
      return h("div", { class: "webhook-secret", role: "status" },
        h("p", { class: "flag" }, M.t("webhook.shown_once")),
        h("p", null, M.tn("webhook.payload_url", { url: h("code", null, shown.url) })),
        h("p", null, M.tn("webhook.secret_line", { secret: h("code", { class: "webhook-secret-value" }, shown.secret) }), " ", copy));
    }
    async function draw(shown) {
      let w;
      try {
        w = await M.api.get(path);
      } catch (err) {
        const again = h("button", { type: "button", class: "small" }, M.t("webhook.read_again"));
        again.addEventListener("click", () => draw(shown));
        append(clear(body), h("p", { class: "send-status failed" }, M.t("webhook.read_failed", { reason: err.message }), " ", again),
          shown ? secretBlock(shown) : null);
        return;
      }
      clear(body);
      append(body, h("dl", { class: "facts" },
        h("dt", null, M.t("webhook.secret")), h("dd", null, !w.configured ? M.t("webhook.secret.none")
          : w.rotated_at ? M.t("webhook.secret.rotated", { when: formatTime(w.rotated_at) })
            : w.created_at ? M.t("webhook.secret.set_at", { when: formatTime(w.created_at) }) : M.t("webhook.secret.set")),
        h("dt", null, M.t("webhook.last")), h("dd", null, w.last_delivery_at ? [formatTime(w.last_delivery_at), w.last_result ? " · " + w.last_result : null] : M.t("webhook.last.none"))));
      if (shown) append(body, secretBlock(shown));
      const make = h("button", { type: "button", class: "primary" }, w.configured ? M.t("webhook.rotate") : M.t("webhook.create"));
      make.addEventListener("click", () => act(async () => {
        if (w.configured && !window.confirm(M.t("webhook.rotate.confirm"))) return;
        status.busy(M.t("webhook.making"));
        try {
          const made = await M.api.post(path + "/secret", {});
          status.done();
          await draw(made);
        } catch (err) { status.fail(M.t("webhook.not_made"), err); }
      }));
      const remove = w.configured ? h("button", { type: "button" }, M.t("webhook.remove")) : null;
      if (remove) {
        remove.addEventListener("click", () => act(async () => {
          if (!window.confirm(M.t("webhook.remove.confirm"))) return;
          status.busy(M.t("webhook.removing"));
          try {
            await M.api.del(path + "/secret");
            status.done();
            await draw(null);
          } catch (err) { status.fail(M.t("webhook.not_removed"), err); }
        }));
      }
      append(body, h("div", { class: "actions" }, remove, make));
    }
    draw(null);
    return box;
  }

  M.tickerSettings = { tickerForm, webhookPanel, parseImplementers, contains };
})(window.Maity);
