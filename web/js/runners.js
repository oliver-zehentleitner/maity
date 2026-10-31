// (8) Runners (/runners): the small services on the operator's own
// machines that start agents for the projects they are allowed in
// (docs/api.md §15). The hub never starts anything itself; a runner does,
// within what its own configuration allows. This view pairs a runner (the
// line shown once, with the starter configuration and the steps that make
// it start), lists them in plain words, and renames, revokes, re-pairs and
// removes them. What a runner advertises is data and rendered as text.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  const PRESENCE_MS = 30000;
  // A runner's name follows the rule for handles.
  const NAME_PATTERN = M.dom.NAME_RULES.handle.pattern;
  const NAME = M.dom.NAME_RULES.handle.test;
  // Read when shown: the rule's text is the catalog's (a getter in dom.js).
  const nameRule = () => M.dom.NAME_RULES.handle.text;
  // The CLI as published on PyPI; the runner commands are part of it.
  const CLI_INSTALL = "pipx install maity";
  const CONFIG_PATH = "~/.config/maity-runner/runner.toml";

  // ---- plain words for what a runner advertises (shared with Project → Runners)

  const TOOLS = {
    "claude-code": "Claude Code", codex: "Codex", opencode: "opencode", pi: "pi", hermes: "Hermes",
    kimi: "Kimi Code", cline: "Cline", omp: "oh-my-pi", get stub() { return M.t("runners.tool.stub"); },
  };
  const toolName = (id) => (Object.hasOwn(TOOLS, id) ? TOOLS[id] : id);
  const MODES = {
    get interactive() { return M.t("runners.mode.interactive"); },
    get supervised() { return M.t("runners.mode.supervised"); },
  };
  // Names in a sentence: "a, b, c" in English, in the catalog's language.
  const names = (list) => M.fmt.list(list);

  // local: one machine; ssh: hosts; k8s: a pool of pods.
  function backendLabel(runner) {
    const c = runner.capabilities;
    if (!c) return M.t("runners.backend.unreported");
    const targets = names((c.targets || []).map((t) => t.name));
    if (c.backend === "local") return M.t("runners.backend.local");
    if (c.backend === "ssh") return M.t("runners.backend.ssh", { targets });
    if (c.backend === "k8s") return M.t("runners.backend.k8s", { targets });
    return c.backend;
  }

  function presenceText(runner) {
    if (runner.removed_at) return M.t("runners.presence.removed", { ago: formatAgo(runner.removed_at) });
    if (runner.credential_state === "revoked") return M.t("runners.presence.revoked");
    if (runner.credential_state === "none") return M.t("runners.presence.unpaired");
    if (runner.presence === "online") return M.t("runners.presence.online");
    const away = runner.presence === "away";
    if (!runner.last_seen_at) return away ? M.t("runners.presence.away_never") : M.t("runners.presence.offline_never");
    const ago = formatAgo(runner.last_seen_at);
    return away ? M.t("runners.presence.away_seen", { ago }) : M.t("runners.presence.offline_seen", { ago });
  }

  const presenceClass = (runner) => (runner.credential_state !== "active" || runner.removed_at ? "revoked" : (runner.presence || "offline"));

  // "Agents on this machine run as user oliver, with the runner, together."
  function isolationSentence(runner, target) {
    const name = runner.capabilities.backend === "local" ? runner.name : target.name;
    const iso = target.isolation || {};
    if (iso.kind === "shared_user") {
      const user = iso.user || "?";
      return iso.runner_separate ? M.t("runners.isolation.shared_separate", { name, user }) : M.t("runners.isolation.shared", { name, user });
    }
    if (iso.kind === "own_user") return M.t("runners.isolation.own_user", { name });
    if (iso.kind === "pod") return M.t("runners.isolation.pod", { name });
    return M.t("runners.isolation.unreported", { name, kind: iso.kind || "unknown" });
  }

  function targetLine(runner, target) {
    const c = runner.capabilities;
    let line = M.t("runners.target.running", { running: target.running, count: target.max_agents });
    if (target.reachable === false) {
      line = target.unreachable_since ? M.t("runners.target.unreachable_since", { line, ago: formatAgo(target.unreachable_since) })
        : M.t("runners.target.unreachable", { line });
    }
    if (c.backend === "local") return line;
    return c.backend === "ssh" ? M.t("runners.target.host", { name: target.name, line }) : M.t("runners.target.pool", { name: target.name, line });
  }

  function toolLine(runner, tool) {
    if (tool.available === false) {
      const values = { tool: toolName(tool.id), runner: runner.name, reason: tool.reason };
      const said = tool.reason === "binary_not_found" ? M.t("runners.tool.not_installed", values)
        : tool.reason === "version_failed" ? M.t("runners.tool.no_version", values)
          : tool.reason ? M.t("runners.tool.unavailable_reason", values) : M.t("runners.tool.unavailable", values);
      return h("li", { class: "unavailable" }, said);
    }
    const bounds = tool.confinement === "allowlist" ? M.t("runners.tool.allowlist")
      : tool.confinement === "pod" ? M.t("runners.tool.pod")
        : tool.confinement === "none" ? M.t("runners.tool.tests_only") : tool.confinement;
    const parts = [tool.sandbox === "on" ? M.t("runners.tool.sandboxed", { bounds }) : bounds,
      // "; or ": a mode's own words hold a comma.
      (tool.modes || []).map((m) => (Object.hasOwn(MODES, m) ? MODES[m] : m)).join(M.t("runners.tool.or"))];
    if ((tool.models || []).length) parts.push(M.t("runners.tool.models", { models: names(tool.models) }));
    return h("li", null, h("strong", null, toolName(tool.id)), (tool.version ? " " + tool.version : "") + " · " + parts.join(" · "));
  }

  function allows(c) {
    const values = {
      projects: (c.projects || []).length ? names(c.projects) : M.t("runners.caps.none"),
      repositories: (c.repositories || []).length ? names(c.repositories) : M.t("runners.caps.none"),
    };
    return c.require_local_approval ? M.t("runners.caps.allows_approval", values) : M.t("runners.caps.allows", values);
  }

  // What a runner can do, in words: hosts or pools, tools, how agents are kept apart.
  function capabilities(runner) {
    const c = runner.capabilities;
    if (!c) return h("p", { class: "muted" }, M.t("runners.caps.unreported"));
    return h("div", { class: "runner-caps" },
      h("ul", { class: "runner-targets" }, (c.targets || []).map((t) => h("li", null, targetLine(runner, t)))),
      h("h4", null, M.t("runners.caps.tools")),
      (c.harnesses || []).length ? h("ul", { class: "runner-tools" }, c.harnesses.map((t) => toolLine(runner, t)))
        : h("p", { class: "muted" }, M.t("runners.caps.no_tools")),
      h("h4", null, M.t("runners.caps.isolation")),
      h("ul", { class: "runner-isolation" }, (c.targets || []).map((t) => h("li", null, isolationSentence(runner, t)))),
      h("p", { class: "muted" }, allows(c)));
  }

  M.runnerWords = { toolName, backendLabel, presenceText, presenceClass, capabilities, isolationSentence, MODES };

  // ---- the starter configuration --------------------------------------------

  // The file's text stays English: it is the runner's configuration, which
  // tools/starter_configs.py checks as written, not words of the page.
  // From what the dashboard knows: this hub, the projects the human
  // administers with their repositories. No secret: the credential comes
  // from the pairing line and is written by maity runner pair.
  // A TOML basic string: quote, backslash, control characters and DEL
  // escaped; a lone surrogate, which TOML cannot carry, becomes U+FFFD.
  const q = (s) => "\"" + String(s).replace(/[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]/g, "\ufffd")
    .replace(/["\\\u0000-\u001f\u007f]/g, (c) => (c === "\"" || c === "\\" ? "\\" + c : "\\u" + c.charCodeAt(0).toString(16).padStart(4, "0"))) + "\"";

  // Only the keys without a default (design v2 §5.1): the runner refuses
  // unknown keys, so the less it says, the less can disagree with it.
  function starterConfig(hubUrl, projects) {
    const repos = projects.map((p) => p.repository && p.repository.url).filter(Boolean)
      .map((u) => u.replace(/^https:\/\//, "").replace(/\.git$/, "").replace(/\/$/, ""));
    return [
      "# Maity runner: " + CONFIG_PATH,
      "# Generated by the dashboard. It holds no secret; maity runner pair writes the credential.",
      "",
      "[hub]",
      "url = " + q(hubUrl),
      "",
      "[limits]",
      "projects = [" + projects.map((p) => q(p.full_name)).join(", ") + "]" + (projects.length ? "" : "   # none chosen: it starts nothing until you add one"),
      "repositories = [" + repos.map(q).join(", ") + "]",
      "",
      "[backend]",
      "kind = \"local\"",
      "",
      "[backend.local]",
      "layout = \"single\"   # agents run as your user, together",
      "",
      "[harness.claude-code]",
      "modes = [\"interactive\", \"supervised\"]",
      "models = [\"opus\", \"sonnet\"]",
      "",
    ].join("\n");
  }

  function copyButton(textOf, label) {
    const b = h("button", {
      type: "button",
      class: "small",
      onclick: async () => {
        try {
          await navigator.clipboard.writeText(textOf());
          b.textContent = M.t("runners.copy.done");
        } catch (err) {
          b.textContent = M.t("runners.copy.failed");
        }
      },
    }, label || M.t("runners.copy.label"));
    return b;
  }

  // The command that writes the configuration. set -C: an existing one is
  // never overwritten, the shell says so; umask 077: the file decides what
  // agents may touch, so only its owner may change it.
  const writeCommand = (config) => "mkdir -p ~/.config/maity-runner && (set -C; umask 077; cat > " + CONFIG_PATH + ") <<'EOF'\n" + config + "EOF";

  // The panel that makes a pairing end in a runner that starts.
  function pairSteps(enrollment, config, onHide) {
    const heredoc = config && writeCommand(config);
    return h("div", { class: "pair-steps flag", "aria-live": "polite" },
      h("p", null, h("strong", null, M.t("runners.pair.where"))),
      h("ol", null,
        h("li", null, M.t("runners.pair.install"), h("pre", { class: "paste-line" }, CLI_INSTALL), copyButton(() => CLI_INSTALL),
          h("p", { class: "hint" }, M.t("runners.pair.install_hint"))),
        config
          ? h("li", null, M.t("runners.pair.save", { path: CONFIG_PATH }),
          h("pre", { class: "runner-config", tabindex: "0", "aria-label": M.t("runners.pair.config_label") }, config),
          copyButton(() => config, M.t("runners.pair.copy_config")), " ", copyButton(() => heredoc, M.t("runners.pair.copy_command")))
          : h("li", null, M.t("runners.pair.keep_config")),
        h("li", { class: "pair-line-step" }, M.t("runners.pair.line", { time: formatTime(enrollment.expires_at) }),
          h("pre", { class: "paste-line" }, enrollment.pair_line), copyButton(() => enrollment.pair_line)),
        h("li", null, M.tn("runners.pair.check", { command: h("code", null, "maity runner check") })),
        h("li", null, M.tn("runners.pair.start", { command: h("code", null, "maity runner serve") }))),
      h("p", { class: "muted pair-wait" }, M.t("runners.pair.waiting")),
      h("div", { class: "actions" }, h("button", { type: "button", onclick: onHide }, M.t("runners.hide"))));
  }

  // ---- the view --------------------------------------------------------------

  M.views.runners = async function (ctx, root) {
    const [runners, enrollments, projects] = await Promise.all([
      M.api.getAll("/runners"),
      M.api.getAll("/runners/enrollments"),
      M.api.get("/projects"),
    ]);
    const admin = new Set(ctx.projects.filter((p) => M.trust.governs(p)).map((p) => p.full_name));
    const adminProjects = (projects.items || []).filter((p) => admin.has(p.full_name));
    const status = M.statusLine();
    const list = h("div", { class: "runners" });
    const pending = h("div", { class: "enrollments" });
    const panel = h("div", { class: "pair-panel" });
    // The pairing on screen: {name, expires_at}, or {runner_id, credential}
    // for a re-pair, which is done when the credential is another one.
    let waitingFor = null;

    function drawEnrollments(items) {
      const open = items.filter((e) => !e.used_at && !e.revoked_at && !e.burned && Date.parse(e.expires_at) > Date.now());
      clear(pending);
      if (!open.length) return;
      append(pending, h("h3", null, M.t("runners.open.title")), h("ul", { class: "joins" }, open.map((e) => h("li", null,
        h("code", null, e.id), " " + M.t("runners.open.item", { name: e.name || M.t("runners.open.repair_of", { id: e.runner_id }), time: formatTime(e.expires_at) }),
        h("button", {
          type: "button",
          class: "danger",
          onclick: async () => {
            status.busy(M.t("runners.busy.revoking"));
            try {
              await M.api.del("/runners/enrollments/" + encodeURIComponent(e.id));
              drawEnrollments((await M.api.getAll("/runners/enrollments")).items);
              status.done();
            } catch (err) {
              status.fail(M.t("runners.failed.not_revoked"), err);
            }
          },
        }, M.t("runners.revoke"))))));
    }

    // busy: what the status line says meanwhile; failed: its prefix to the hub's words.
    async function act(busy, failed, call, after) {
      status.busy(busy);
      try {
        const answer = await call();
        status.done();
        if (after) after(answer);
        await reload();
      } catch (err) {
        status.fail(failed, err);
      }
    }

    function runnerCard(r) {
      const id = "runner-name-" + r.id;
      const nameInput = h("input", { id, value: r.name, pattern: NAME_PATTERN, required: true });
      const rename = h("form", {
        class: "inline-form rename",
        onsubmit: (e) => {
          e.preventDefault();
          const name = nameInput.value.trim();
          if (!NAME.test(name)) { status.fail(M.t("runners.failed.not_renamed"), { message: nameRule() }); return; }
          if (name === r.name) return;
          act(M.t("runners.busy.renaming"), M.t("runners.failed.renaming"), () => M.api.patch("/runners/" + encodeURIComponent(r.id), { name }));
        },
      }, h("label", { for: id }, M.t("runners.name")), nameInput, h("button", { type: "submit", class: "small" }, M.t("runners.rename")));
      const cred = r.credential;
      return h("article", { class: "runner", "aria-label": r.name },
        h("header", null,
          h("span", { class: "dot " + presenceClass(r) }),
          h("h3", null, r.name),
          h("span", { class: "presence " + presenceClass(r) }, presenceText(r)),
          h("span", { class: "muted" }, " · " + backendLabel(r) + (r.version ? " · " + r.version : ""))),
        r.projects && r.projects.length
          ? h("p", null, M.t("runners.allowed_in", { projects: names(r.projects) }))
          : h("p", { class: "muted" }, M.t("runners.allowed_nowhere")),
        capabilities(r),
        cred
          ? h("p", { class: "muted" }, M.tn("runners.credential", { id: h("code", null, cred.id), time: formatTime(cred.created_at) }),
            cred.last_used_at ? " · " + M.t("runners.credential.used", { ago: formatAgo(cred.last_used_at) }) : "",
            cred.revoked_at ? " · " + (cred.revoked_reason ? M.t("runners.credential.revoked_why", { time: formatTime(cred.revoked_at), reason: cred.revoked_reason })
              : M.t("runners.credential.revoked", { time: formatTime(cred.revoked_at) })) : "")
          : null,
        h("div", { class: "runner-actions" },
          rename,
          h("button", {
            type: "button",
            onclick: () => act(M.t("runners.busy.repairing"), M.t("runners.failed.repairing"), () => M.api.post("/runners/enrollments", { runner_id: r.id }),
              (e) => showPairing(e, null, { runner_id: r.id, name: r.name, expires_at: e.expires_at, credential: cred && cred.id })),
          }, M.t("runners.repair")),
          r.credential_state === "active"
            ? h("button", {
              type: "button",
              class: "danger separated",
              onclick: () => {
                if (!window.confirm(M.t("runners.confirm.revoke", { name: r.name }))) return;
                act(M.t("runners.busy.revoking"), M.t("runners.failed.revoking"), () => M.api.post("/runners/" + encodeURIComponent(r.id) + "/revoke", {}));
              },
            }, M.t("runners.revoke"))
            : null,
          h("button", {
            type: "button",
            class: "danger" + (r.credential_state === "active" ? "" : " separated"),
            onclick: () => {
              if (!window.confirm(M.t("runners.confirm.remove", { name: r.name }))) return;
              act(M.t("runners.busy.removing"), M.t("runners.failed.removing"), () => M.api.del("/runners/" + encodeURIComponent(r.id)), showRemoved);
            },
          }, M.t("runners.remove"))));
    }

    function showRemoved(answer) {
      const still = answer.still_running || [];
      clear(panel);
      append(panel, h("div", { class: "flag", role: "status" },
        h("p", null, h("strong", null, M.t("runners.removed.title", { name: answer.name }))),
        still.length
          ? [h("p", null, M.tn("runners.removed.still", { command: h("code", null, "maity runner stop-all") })),
          h("ul", null, still.map((p) => h("li", null, (p.agent && (p.agent.display_name || p.agent.handle)) || p.id,
            p.reported ? " · " + p.reported.state : "")))]
          : h("p", null, M.t("runners.removed.nothing")),
        h("div", { class: "actions" }, h("button", { type: "button", onclick: () => clear(panel) }, M.t("runners.hide")))));
    }

    function showPairing(enrollment, config, waiting) {
      waitingFor = waiting;
      clear(panel);
      append(panel, pairSteps(enrollment, config, () => { waitingFor = null; clear(panel); }));
    }

    function pairForm() {
      const name = h("input", { id: "pair-name", required: true, pattern: NAME_PATTERN, maxlength: "31", placeholder: M.t("runners.pair.name_placeholder"),
        autocomplete: "off", spellcheck: "false", "aria-describedby": "pair-name-rule" });
      const ttl = h("select", { id: "pair-ttl" },
        [900, 600, 300].map((v) => h("option", { value: String(v) }, M.t("runners.pair.minutes", { count: v / 60 }))));
      ttl.value = "900";
      const boxes = adminProjects.map((p) => {
        const box = h("input", { type: "checkbox", id: "pair-attach-" + p.full_name.replace("/", "-") });
        box.checked = true;
        return { p, box };
      });
      return h("form", {
        class: "inline-form pair-form",
        onsubmit: (e) => {
          e.preventDefault();
          const n = name.value.trim();
          if (!NAME.test(n)) { status.fail(M.t("runners.failed.no_line"), { message: M.t("runners.pair.name_rule", { rule: nameRule() }) }); name.focus(); return; }
          const attach = boxes.filter((b) => b.box.checked).map((b) => b.p.full_name);
          const chosen = adminProjects.filter((p) => attach.includes(p.full_name));
          const create = () => M.api.post("/runners/enrollments", { name: n, ttl_seconds: Number(ttl.value), attach });
          act(M.t("runners.busy.pairing"), M.t("runners.failed.pairing"), create,
            (enr) => showPairing(enr, starterConfig(new URL(enr.pair_url).origin, chosen), { name: n, expires_at: enr.expires_at }));
        },
      },
      h("h3", null, M.t("runners.pair.title")),
      h("p", { class: "hint" }, M.t("runners.pair.hint")),
      h("label", { for: "pair-name" }, M.t("runners.pair.name")), name, h("p", { class: "hint", id: "pair-name-rule" }, nameRule()),
      boxes.length ? h("fieldset", { class: "pair-projects" }, h("legend", null, M.t("runners.pair.allow_in")),
        boxes.map(({ p, box }) => h("label", { class: "check", for: box.id }, box, " " + p.name))) : null,
      h("label", { for: "pair-ttl" }, M.t("runners.pair.ttl")), ttl,
      h("button", { type: "submit" }, M.t("runners.pair.submit")));
    }

    function drawRunners(items) {
      clear(list);
      const live = items.filter((r) => !r.removed_at);
      if (!live.length) {
        append(list, h("div", { class: "empty-state" }, h("p", null, M.t("runners.empty"))));
        return;
      }
      live.forEach((r) => append(list, runnerCard(r)));
      // The pairing on screen: say when its runner has paired and come online;
      // once the line is used or expired it leaves the page.
      const wait = panel.querySelector(".pair-wait");
      if (waitingFor && wait) {
        const r = live.find((x) => (waitingFor.runner_id ? x.id === waitingFor.runner_id : x.name === waitingFor.name));
        const paired = r && r.credential_state === "active" && (!waitingFor.runner_id || (r.credential && r.credential.id) !== waitingFor.credential);
        const step = panel.querySelector(".pair-line-step");
        if (paired) {
          wait.textContent = r.presence === "online" ? M.t("runners.paired.online", { name: r.name }) : M.t("runners.paired.offline", { name: r.name });
          wait.className = "ok pair-wait";
          if (step) append(clear(step), M.t("runners.paired.used"));
        } else if (step && Date.parse(waitingFor.expires_at) <= Date.now()) {
          append(clear(step), M.t("runners.paired.expired"));
          wait.textContent = "";
        }
      }
    }

    // The newest read draws: a periodic one still in flight when an action
    // reloads would otherwise answer last and undo what the action shows.
    let reads = 0;
    async function reload() {
      const read = ++reads;
      const [r, e] = await Promise.all([M.api.getAll("/runners"), M.api.getAll("/runners/enrollments")]);
      if (read !== reads) return;
      drawRunners(r.items);
      drawEnrollments(e.items);
    }

    append(root, h("h2", null, M.t("runners.title")),
      h("p", { class: "muted" }, M.t("runners.intro")),
      pairForm(), panel, status.el, pending, list);
    drawRunners(runners.items);
    drawEnrollments(enrollments.items);
    // Presence and capabilities emit no events: re-read them (docs/api.md §15.1).
    // One periodic read at a time: a slow one is not overtaken by the next tick,
    // which would leave every answer discarded and the page old.
    let polling = false;
    ctx.every(PRESENCE_MS, async () => {
      if (polling) return;
      polling = true;
      try {
        await reload();
      } catch (err) {
        status.fail(M.t("runners.failed.refresh"), err);
      } finally {
        polling = false;
      }
    });
  };

  M.runnerStarterConfig = starterConfig;
  M.runnerConfigCommand = writeCommand;
})(window.Maity);
