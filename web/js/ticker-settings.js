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
      if (!m) { errors.push("line " + (i + 1) + ": write it as '<section>: <token> <token>', e.g. '8: area:hub/'"); return; }
      const tokens = m[2].split(/\s+/).filter(Boolean);
      const bad = tokens.filter((t) => !TOKEN.test(t));
      if (bad.length) errors.push("line " + (i + 1) + ": " + bad.join(", ") + " is no token (area:<path>, member:<id>, role:<role>, trust:<trust>)");
      if (tokens.length > TOKENS_MAX) errors.push("line " + (i + 1) + ": at most " + TOKENS_MAX + " tokens");
      map[m[1]] = tokens;
    });
    if (Object.keys(map).length > KEYS_MAX) errors.push("at most " + KEYS_MAX + " sections");
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
      unresolvedBox.textContent = lost.length ? "Names nobody now: " + lost.join(", ") + "." : "";
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
        if (paths.length > FILES_MAX) errors.push("at most " + FILES_MAX + " contract files");
        if (errors.length) { status.fail("Not saved: ", { message: errors.join("; ") }); return; }
        // Sent whole (§6.1): what the form leaves out is gone.
        save({ settings: { ticker: { enabled: enabled.checked, contract_files: paths, contract_implementers: map } } }, "Ticker");
      },
    },
    h("h2", { class: "panel-title" }, "Change ticker"),
    h("label", { class: "check", for: "ticker-enabled" }, enabled, " Announce merges, decisions, releases and deploys"),
    h("p", { class: "hint" }, "Off, only posts by hand reach the ticker. Your own follows and mutes: ",
      h("a", { href: ctx.link("ticker") }, "the Ticker"), "."),
    h("label", { for: "ticker-files" }, "Contract files (one path per line)"), files,
    h("label", { for: "ticker-implementers" }, "Who implements which section"), impl,
    h("p", { class: "hint", id: "ticker-implementers-hint" }, "One section per line: its number, a colon, then who: area:<path>, member:<id>, role:<role>, trust:<trust>. "
      + "* stands for every section no line names. Admins hear of every contract change anyway."),
    unresolvedBox,
    mayEdit ? h("button", { type: "submit" }, "Save the ticker") : h("p", { class: "muted" }, "An owner or admin changes these."),
    status.el);
    return form;
  }

  // The forge's webhook (§17.4): set or not, its last delivery; a secret
  // made or rotated is shown once with the address to enter at the forge.
  function webhookPanel(ctx) {
    const box = h("section", { class: "panel webhook", "aria-labelledby": "webhook-title" });
    const body = h("div");
    const status = M.statusLine();
    append(box, h("h2", { class: "panel-title", id: "webhook-title" }, "Forge webhook"),
      h("p", { class: "hint" }, "With a webhook the forge tells the hub of merges at once; without one the hub finds them on its next probe."),
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
      const copy = h("button", { type: "button", class: "small" }, "Copy the secret");
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(shown.secret); copy.textContent = "Copied"; } catch (err) { copy.textContent = "Copy failed: select it"; }
      });
      return h("div", { class: "webhook-secret", role: "status" },
        h("p", { class: "flag" }, "Shown only now. Enter it at the forge: payload URL as below, content type application/json, this secret."),
        h("p", null, "Payload URL: ", h("code", null, shown.url)),
        h("p", null, "Secret: ", h("code", { class: "webhook-secret-value" }, shown.secret), " ", copy));
    }
    async function draw(shown) {
      let w;
      try {
        w = await M.api.get(path);
      } catch (err) {
        const again = h("button", { type: "button", class: "small" }, "Read it again");
        again.addEventListener("click", () => draw(shown));
        append(clear(body), h("p", { class: "send-status failed" }, "The webhook could not be read: " + err.message, " ", again),
          shown ? secretBlock(shown) : null);
        return;
      }
      clear(body);
      append(body, h("dl", { class: "facts" },
        h("dt", null, "Secret"), h("dd", null, w.configured ? "set" + (w.rotated_at ? ", rotated " + formatTime(w.rotated_at) : w.created_at ? " " + formatTime(w.created_at) : "") : "none"),
        h("dt", null, "Last delivery"), h("dd", null, w.last_delivery_at ? formatTime(w.last_delivery_at) + (w.last_result ? " · " + w.last_result : "") : "none yet")));
      if (shown) append(body, secretBlock(shown));
      const make = h("button", { type: "button", class: "primary" }, w.configured ? "Rotate the secret" : "Create a secret");
      make.addEventListener("click", () => act(async () => {
        if (w.configured && !window.confirm("Rotate the secret? The current one stops working at once; deliveries fail until the forge has the new one.")) return;
        status.busy("Making the secret…");
        try {
          const made = await M.api.post(path + "/secret", {});
          status.done();
          await draw(made);
        } catch (err) { status.fail("Not made: ", err); }
      }));
      const remove = w.configured ? h("button", { type: "button" }, "Remove the secret") : null;
      if (remove) {
        remove.addEventListener("click", () => act(async () => {
          if (!window.confirm("Remove the secret? Deliveries are refused from then on; the hub finds merges on its probe.")) return;
          status.busy("Removing…");
          try {
            await M.api.del(path + "/secret");
            status.done();
            await draw(null);
          } catch (err) { status.fail("Not removed: ", err); }
        }));
      }
      append(body, h("div", { class: "actions" }, remove, make));
    }
    draw(null);
    return box;
  }

  M.tickerSettings = { tickerForm, webhookPanel, parseImplementers, contains };
})(window.Maity);
