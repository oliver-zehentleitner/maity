// (8) Runners (/runners): the small services on the operator's own
// machines that start agents for the projects they are allowed in
// (docs/api.md §15). The hub never starts anything itself; a runner does,
// within what its own configuration allows. This view pairs a runner (the
// line shown once, with the starter configuration and the steps that make
// it start), lists them in plain words, and renames, revokes, re-pairs and
// removes them. What a runner advertises is data and rendered as text.
// Pair a runner is one button at the head that opens the pairing form, as Join an agent opens
// its panel (tsk-raghxwjf3e0e): closed by default, open at once at /runners/pair (the "+"
// menu's Runner, the project's "Pair one" link) and while no runner is paired yet.
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
  // The service way (`maity runner install`, cli/src/maity/runner/install.py): its fixed
  // paths, the home of the user it makes, and where the runner keeps the tools it installs.
  // A command as maity-runner starts in `/` (`cd / &&`), or Claude Code in that user's home:
  // sudo keeps the caller's directory, which maity-runner may not enter (Ubuntu's 0750
  // homes), and Claude Code would ask to trust it (web/context/views.md).
  const SERVICE = {
    config: "/etc/maity-runner/runner.toml",
    home: "/var/lib/maity-runner",
    state: "/var/lib/maity-runner/state",
    workspaces: "/var/lib/maity-runner/workspaces",
    packages: "sudo apt install tmux socat bubblewrap git pipx",
    // `postgresql` brings the server's programs; the cluster apt makes and starts with them is
    // not what a project's scripts use (they start their own), so it is stopped (review A2146).
    checks: "sudo apt install make python3-venv python3-dev build-essential postgresql && sudo systemctl disable --now postgresql",
    cli: "sudo pipx install --global maity",
    start: "sudo systemctl restart maity-runner",
    stop: "sudo systemctl stop maity-runner",
    check: "cd / && sudo -u maity-runner -H maity runner check --config /etc/maity-runner/runner.toml",
    versions: "sudo ls /var/lib/maity-runner/.local/share/maity-runner/tools/claude-code/versions",
    login: "sudo -u maity-runner -H sh -c 'cd && exec /var/lib/maity-runner/.local/share/maity-runner/tools/claude-code/versions/<version>/bin/claude'",
    forge: "cd / && sudo -u maity-runner -H gh auth login",
    forgeGit: "cd / && sudo -u maity-runner -H gh auth setup-git",
    // A re-pair: the runner's credential moved aside, since `pair` refuses while one is there.
    aside: "sudo -u maity-runner mv /var/lib/maity-runner/state/credential /var/lib/maity-runner/state/credential.old",
  };
  // The terminal way's re-pair: the default state directory's credential moved aside.
  const TERMINAL_ASIDE = "mv ~/.local/state/maity-runner/credential ~/.local/state/maity-runner/credential.old";

  // ---- plain words for what a runner advertises (shared with Project → Runners)

  const TOOLS = {
    "claude-code": "Claude Code", codex: "Codex", opencode: "OpenCode", antigravity: "Antigravity",
    pi: "pi", hermes: "Hermes",
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

  // Why a tool the runner lists is offered to no placement: its reason (§15.3) in words. A tool
  // the runner installs itself (§15.16, `capabilities.tools`) is not found while its install
  // runs or after it failed: that is said instead of "not installed" (review A2146).
  function unavailableText(runner, tool) {
    const values = { tool: toolName(tool.id), runner: runner.name, reason: tool.reason };
    const managed = tool.reason === "binary_not_found"
      ? ((runner.capabilities && runner.capabilities.tools) || []).find((t) => t.id === tool.id) : null;
    if (managed && managed.state === "installing") return M.t("runners.tool.installing", values);
    if (managed && managed.state === "failed") {
      return M.t("runners.tool.install_failed", Object.assign({}, values, { reason: managed.reason || "?" }));
    }
    return tool.reason === "binary_not_found" ? M.t("runners.tool.not_installed", values)
      : tool.reason === "version_failed" ? M.t("runners.tool.no_version", values)
        : tool.reason === "login_needed" ? M.t("runners.tool.login_needed", values)
          : tool.reason ? M.t("runners.tool.unavailable_reason", values) : M.t("runners.tool.unavailable", values);
  }

  function toolLine(runner, tool) {
    if (tool.available === false) return h("li", { class: "unavailable" }, unavailableText(runner, tool));
    const bounds = tool.confinement === "allowlist" ? M.t("runners.tool.allowlist")
      : tool.confinement === "pod" ? M.t("runners.tool.pod")
        : tool.confinement === "none" ? M.t("runners.tool.tests_only") : tool.confinement;
    // `sandbox` (codex): the OS sandbox is the whole boundary, so its state is the sentence.
    const kept = tool.confinement === "sandbox"
      ? (tool.sandbox === "on" ? M.t("runners.tool.sandbox_on") : M.t("runners.tool.sandbox_off"))
      : tool.sandbox === "on" ? M.t("runners.tool.sandboxed", { bounds }) : bounds;
    const parts = [kept,
      // "; or ": a mode's own words hold a comma.
      (tool.modes || []).map((m) => (Object.hasOwn(MODES, m) ? MODES[m] : m)).join(M.t("runners.tool.or"))];
    if ((tool.models || []).length) parts.push(M.t("runners.tool.models", { models: names(tool.models) }));
    return h("li", null, h("strong", null, toolName(tool.id)), (tool.version ? " " + tool.version : "") + " · " + parts.join(" · "));
  }

  // Whole sentences, one each: an empty list has a sentence of its own rather than a word put
  // into the list's place ("allows the projects none").
  function allows(c) {
    return [
      (c.projects || []).length ? M.t("runners.caps.projects", { projects: names(c.projects) }) : M.t("runners.caps.projects_none"),
      (c.repositories || []).length ? M.t("runners.caps.repositories", { repositories: names(c.repositories) })
        : M.t("runners.caps.repositories_none"),
      c.require_local_approval ? M.t("runners.caps.approval") : null,
    ].filter(Boolean).join(" ");
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

  M.runnerWords = { toolName, backendLabel, presenceText, presenceClass, capabilities, isolationSentence, unavailableText, MODES };

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
  // `way` "service": the file replaces the one `maity runner install` wrote, so it
  // keeps install's state_dir (where install paired) and workspaces, and the runner
  // installs Claude Code for its user, who has none (web/context/views.md).
  function starterConfig(hubUrl, projects, way) {
    const service = way === "service";
    const repos = projects.map((p) => p.repository && p.repository.url).filter(Boolean)
      .map((u) => u.replace(/^https:\/\//, "").replace(/\.git$/, "").replace(/\/$/, ""));
    return [
      "# Maity runner: " + (service ? SERVICE.config : CONFIG_PATH),
      "# Generated by the dashboard. It holds no secret; the credential is written by maity runner " + (service ? "install" : "pair") + ".",
      "",
      "[hub]",
      "url = " + q(hubUrl),
      ...(service ? ["state_dir = " + q(SERVICE.state)] : []),
      "",
      "[limits]",
      "projects = [" + projects.map((p) => q(p.full_name)).join(", ") + "]" + (projects.length ? "" : "   # none chosen: it starts nothing until you add one"),
      "repositories = [" + repos.map(q).join(", ") + "]",
      "",
      "[backend]",
      "kind = \"local\"",
      "",
      "[backend.local]",
      ...(service ? ["layout = \"single\"", "workspaces = " + q(SERVICE.workspaces)] : ["layout = \"single\"   # agents run as your user, together"]),
      "",
      "[harness.claude-code]",
      ...(service ? ["install = true"] : []),
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
  // The service way replaces the file install wrote, a copy of it kept beside it; root's
  // file, 0644 as install has it, since the service's user must read it. tee writes into
  // install's existing file, so that mode stays under any umask; without install's file,
  // cp -p fails and nothing is written (tools/starter_configs.py runs it under umask 002).
  // Install's own file is copied aside only once: pasted again, the command keeps that copy.
  const writeCommand = (config, way) => (way === "service"
    ? "{ sudo test -e " + SERVICE.config + ".install || sudo cp -p " + SERVICE.config + " " + SERVICE.config + ".install; } && sudo tee " + SERVICE.config + " > /dev/null <<'EOF'\n" + config + "EOF"
    : "mkdir -p ~/.config/maity-runner && (set -C; umask 077; cat > " + CONFIG_PATH + ") <<'EOF'\n" + config + "EOF");
  // A word for the shell in single quotes; a quote in it closed, escaped and opened again.
  const sq = (s) => "'" + String(s).replace(/'/g, "'\\''") + "'";
  // Every pairing line pipes the code in (--code-file -), never on a command line, where
  // other users of the machine could read it; printf is the shell's own.
  const piped = (enrollment, command) => "printf '%s\\n' " + sq(enrollment.code) + " | " + command + " " + sq(enrollment.pair_url) + " --code-file -";
  const installLine = (enrollment) => piped(enrollment, "sudo maity runner install");
  const pairLine = (enrollment) => piped(enrollment, "maity runner pair");
  // The service's re-pair: pair again as maity-runner, into install's state directory.
  const servicePairLine = (enrollment) => "cd / && " + piped(enrollment, "sudo -u maity-runner -H maity runner pair") + " --config " + SERVICE.config;

  // A command to paste, with its copy button.
  const pasteLine = (command) => [h("pre", { class: "paste-line" }, command), copyButton(() => command)];

  function configStep(text, config, way) {
    const heredoc = writeCommand(config, way);
    return [text, h("pre", { class: "runner-config", tabindex: "0", "aria-label": M.t("runners.pair.config_label") }, config),
      copyButton(() => config, M.t("runners.pair.copy_config")), " ", copyButton(() => heredoc, M.t("runners.pair.copy_command"))];
  }

  // In a terminal: pair, configure, check and serve as the person's own user (Linux and macOS).
  function terminalSteps(enrollment, config) {
    return h("ol", { class: "pair-way-terminal" },
      h("li", null, M.t("runners.pair.install"), pasteLine(CLI_INSTALL),
        h("p", { class: "hint" }, M.t("runners.pair.install_hint"))),
      config ? h("li", null, configStep(M.t("runners.pair.save", { path: CONFIG_PATH }), config, "terminal"))
        : h("li", null, M.t("runners.pair.keep_config"), " ", M.t("runners.pair.aside"), pasteLine(TERMINAL_ASIDE)),
      h("li", { class: "pair-line-step" }, M.t("runners.pair.line", { time: formatTime(enrollment.expires_at) }), pasteLine(pairLine(enrollment))),
      h("li", null, M.tn("runners.pair.check", { command: h("code", null, "maity runner check") })),
      h("li", null, M.tn("runners.pair.start", { command: h("code", null, "maity runner serve") })));
  }

  // As a service (Linux, systemd): `maity runner install` makes the user, the files and the
  // unit and pairs; the steps around it are what install cannot do (docs/runners.md).
  function serviceSteps(enrollment, config) {
    const line = installLine(enrollment);
    return h("ol", { class: "pair-way-service" },
      h("li", null, M.t("runners.pair.service.packages"), pasteLine(SERVICE.packages),
        h("p", { class: "hint" }, M.t("runners.pair.service.packages_hint")),
        h("p", null, M.t("runners.pair.service.checks")), pasteLine(SERVICE.checks),
        h("p", { class: "hint" }, M.t("runners.pair.service.checks_hint"))),
      h("li", null, M.t("runners.pair.service.cli"), pasteLine(SERVICE.cli),
        h("p", { class: "hint" }, M.t("runners.pair.service.cli_hint"))),
      h("li", null,
        h("div", { class: "pair-line-step" }, M.t("runners.pair.service.install", { time: formatTime(enrollment.expires_at) }), pasteLine(line)),
        h("p", { class: "hint" }, M.t("runners.pair.service.install_hint", { home: SERVICE.home, path: SERVICE.config }))),
      h("li", null, configStep(M.t("runners.pair.service.save", { path: SERVICE.config }), config, "service"),
        h("p", { class: "hint" }, M.t("runners.pair.service.save_hint"))),
      h("li", null, M.t("runners.pair.service.start"), pasteLine(SERVICE.start)),
      ...afterStart());
  }

  // The tool's and the forge's login, then the check: with install = true the runner installs
  // Claude Code after its start, and check runs Claude Code headless, which needs the login.
  const afterStart = () => [
    h("li", null, M.t("runners.pair.service.login"), pasteLine(SERVICE.versions), pasteLine(SERVICE.login),
      h("p", { class: "hint" }, M.t("runners.pair.service.login_hint", { home: SERVICE.home }))),
    h("li", null, M.t("runners.pair.service.forge"), pasteLine(SERVICE.forge), pasteLine(SERVICE.forgeGit),
      h("p", { class: "hint" }, M.t("runners.pair.service.forge_hint"))),
    h("li", null, M.t("runners.pair.service.check"), pasteLine(SERVICE.check)),
  ];

  // A service's re-pair: the service stopped, its credential moved aside, paired again as
  // maity-runner with install's configuration (so into install's state directory), started.
  function serviceRepairSteps(enrollment) {
    return h("ol", { class: "pair-way-service" },
      h("li", null, M.t("runners.pair.service.repair_stop"), pasteLine(SERVICE.stop), pasteLine(SERVICE.aside)),
      h("li", { class: "pair-line-step" }, M.t("runners.pair.service.repair_line", { time: formatTime(enrollment.expires_at) }), pasteLine(servicePairLine(enrollment))),
      h("li", null, M.t("runners.pair.service.start"), pasteLine(SERVICE.start)),
      h("li", null, M.t("runners.pair.service.check"), pasteLine(SERVICE.check)));
  }

  // The panel that makes a pairing end in a runner that starts. The person chooses the way,
  // the service by default; the dashboard cannot tell the runner's machine from the browser's,
  // so the person says which (web/context/views.md). A re-pair keeps its configuration
  // (`configFor` null) and pairs again the way the runner runs.
  function pairSteps(enrollment, configFor, onHide) {
    const terminal = terminalSteps(enrollment, configFor && configFor("terminal"));
    const service = configFor ? serviceSteps(enrollment, configFor("service")) : serviceRepairSteps(enrollment);
    let choice = null;
    if (service) {
      terminal.hidden = true;
      const radio = (way, label) => {
        const input = h("input", { type: "radio", name: "pair-way", id: "pair-way-" + way, value: way,
          onchange: () => { service.hidden = way !== "service"; terminal.hidden = way === "service"; } });
        input.checked = way === "service";
        return h("label", { class: "check", for: input.id }, input, " " + label);
      };
      choice = h("fieldset", { class: "pair-way" }, h("legend", null, M.t("runners.pair.way")),
        radio("service", M.t("runners.pair.way_service")), radio("terminal", M.t("runners.pair.way_terminal")));
    }
    return h("div", { class: "pair-steps flag", "aria-live": "polite" },
      h("p", null, h("strong", null, M.t("runners.pair.where"))),
      choice, service, terminal,
      h("p", { class: "muted pair-wait" }, M.t("runners.pair.waiting")),
      h("div", { class: "actions" }, h("button", { type: "button", onclick: onHide }, M.t("runners.hide"))));
  }

  // ---- the view --------------------------------------------------------------

  // args: ["pair"] (/runners/pair) opens the pairing form at once, its name field focused.
  M.views.runners = async function (ctx, root, args) {
    const [runners, enrollments, projects] = await Promise.all([
      M.api.getAll("/runners"),
      M.api.getAll("/runners/enrollments"),
      M.api.get("/projects"),
    ]);
    const admin = new Set(ctx.projects.filter((p) => M.trust.governs(p)).map((p) => p.full_name));
    const adminProjects = (projects.items || []).filter((p) => admin.has(p.full_name));
    const status = M.statusLine();
    // Pairing mints a credential (§2.8.4): the second factor is asked for here when the hub wants it.
    const stepSlot = h("div", { class: "step-up-slot", hidden: true });
    const pairCall = (body) => M.stepUp.run(() => M.api.post("/runners/enrollments", body), stepSlot, M.t("runners.pair.step_up"));
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
        if (err && err.code === "cancelled") status.done();
        else status.fail(failed, err);
      }
    }

    // The agents on a runner of one's own, in every project it is attached to (§15.3), as the
    // runner owner's line: Stop and Remove are the owner's in any project, a member there or
    // not (§15.6); a `foreign` one was placed by someone else before only the owner could.
    const linesOf = new Map();
    const placementPath = (line) => "/projects/" + line.project.split("/").map(encodeURIComponent).join("/")
      + "/placements/" + encodeURIComponent(line.id);
    function agentsOn(r) {
      const lines = linesOf.get(r.id);
      if (!lines) return null;
      return h("section", { class: "runner-placements", "aria-label": M.t("runners.placements.title", { name: r.name }) },
        h("h4", null, M.t("runners.placements.title", { name: r.name })),
        lines.length ? h("ul", null, lines.map((line) => {
          const words = { agent: line.agent.handle, project: line.project };
          return h("li", null,
            // The instance as `handle#id` (§15.3): two of one agent on this runner told apart;
            // the owner's line carries no clone. None before the first pickup.
            M.tn("runners.placements.line", { agent: h("strong", { translate: "no" }, line.agent.handle,
              line.instance ? h("span", { class: "member-instance muted" }, "#" + line.instance) : null), project: line.project }),
            h("span", { class: "muted" }, line.instance ? null : [" · ", M.t("placements.no_instance")],
              " · ", line.desired === "running" ? M.t("runners.placements.running") : M.t("runners.placements.stopped"),
              line.state ? [" · ", M.t("runners.placements.reported", { state: line.state })] : null,
              line.foreign ? [" · ", M.t("runners.placements.foreign")] : null),
            " ",
            line.desired === "running" ? h("button", { type: "button", class: "small", "aria-label": M.t("runners.placements.stop.label", words),
              onclick: () => act(M.t("runners.busy.stopping_agent"), M.t("runners.failed.stopping_agent"),
                () => M.api.patch(placementPath(line), { desired: "stopped" })) }, M.t("runners.placements.stop")) : null,
            " ",
            h("button", { type: "button", class: "small danger", "aria-label": M.t("runners.placements.remove.label", words),
              onclick: () => {
                if (!window.confirm(M.t("runners.placements.remove.ask", words))) return;
                act(M.t("runners.busy.removing_agent"), M.t("runners.failed.removing_agent"), () => M.api.del(placementPath(line)));
              } }, M.t("runners.placements.remove")));
        })) : h("p", { class: "muted" }, M.t("runners.placements.empty")));
    }
    async function readLines(items) {
      const own = items.filter((r) => !r.removed_at && r.owner_id === ctx.me.id);
      const read = await Promise.all(own.map((r) => M.api.getAll("/runners/" + encodeURIComponent(r.id) + "/placements")
        .then((answer) => [r.id, answer.items], () => [r.id, null])));
      linesOf.clear();
      read.forEach(([id, lines]) => { if (lines) linesOf.set(id, lines); });
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
        agentsOn(r),
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
            onclick: () => act(M.t("runners.busy.repairing"), M.t("runners.failed.repairing"), () => pairCall({ runner_id: r.id }),
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
          h("ul", null, still.map((id) => h("li", null, h("code", null, id))))]
          : h("p", null, M.t("runners.removed.nothing")),
        h("div", { class: "actions" }, h("button", { type: "button", onclick: () => clear(panel) }, M.t("runners.hide")))));
    }

    function showPairing(enrollment, configFor, waiting) {
      waitingFor = waiting;
      clear(panel);
      append(panel, pairSteps(enrollment, configFor, () => { waitingFor = null; clear(panel); }));
    }

    let pairName = null; // the form's name field, where the focus goes when it opens
    function pairForm() {
      const name = h("input", { id: "pair-name", required: true, pattern: NAME_PATTERN, maxlength: "31", placeholder: M.t("runners.pair.name_placeholder"),
        autocomplete: "off", spellcheck: "false", "aria-describedby": "pair-name-rule" });
      pairName = name;
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
          const create = () => pairCall({ name: n, ttl_seconds: Number(ttl.value), attach });
          act(M.t("runners.busy.pairing"), M.t("runners.failed.pairing"), create,
            (enr) => showPairing(enr, (way) => starterConfig(new URL(enr.pair_url).origin, chosen, way), { name: n, expires_at: enr.expires_at }));
        },
      },
      h("h3", null, M.t("runners.pair.title")),
      h("p", { class: "hint" }, M.t("runners.pair.hint")),
      h("label", { for: "pair-name" }, M.t("runners.pair.name")), name, h("p", { class: "hint", id: "pair-name-rule" }, nameRule()),
      boxes.length ? h("fieldset", { class: "pair-projects" }, h("legend", null, M.t("runners.pair.allow_in")),
        boxes.map(({ p, box }) => h("label", { class: "check", for: box.id }, box, " " + p.name))) : null,
      h("label", { for: "pair-ttl" }, M.t("runners.pair.ttl")), ttl,
      h("div", { class: "actions" },
        h("button", { type: "button", class: "pair-cancel", onclick: () => closePair(true) }, M.t("runners.pair.cancel")),
        h("button", { type: "submit" }, M.t("runners.pair.submit"))));
    }

    // Pair a runner at the head: a disclosure button for the form under it (aria-expanded,
    // aria-controls). Opened by the button, the focus goes to the name; Cancel and a second
    // press close it, the focus back on the button. What is typed stays across a close.
    const formSlot = h("div", { class: "pair-form-slot", id: "pair-form-slot" }, pairForm());
    const pairOpen = h("button", { type: "button", class: "primary pair-open", "aria-expanded": "false", "aria-controls": "pair-form-slot" },
      M.t("runners.pair.title"));
    function openPair(focus) {
      formSlot.hidden = false;
      pairOpen.setAttribute("aria-expanded", "true");
      if (!focus) return;
      // On a page the router has not attached yet (a direct /runners/pair), the focus waits
      // until it is in the document, as js/join.js's focusSoon does.
      const name = pairName;
      if (name.isConnected === false) window.setTimeout(() => { if (name.isConnected !== false) name.focus(); }, 0);
      else name.focus();
    }
    function closePair(refocus) {
      formSlot.hidden = true;
      pairOpen.setAttribute("aria-expanded", "false");
      if (refocus) pairOpen.focus();
    }
    pairOpen.addEventListener("click", () => (formSlot.hidden ? openPair(true) : closePair(false)));
    formSlot.hidden = true;

    function drawRunners(items) {
      clear(list);
      const live = items.filter((r) => !r.removed_at);
      if (!live.length) append(list, h("div", { class: "empty-state" }, h("p", null, M.t("runners.empty"))));
      live.forEach((r) => append(list, runnerCard(r)));
      // The pairing on screen, also while no runner is paired yet: say when its runner has paired and come online;
      // once the line is used or expired it leaves the page.
      const wait = panel.querySelector(".pair-wait");
      if (waitingFor && wait) {
        const r = live.find((x) => (waitingFor.runner_id ? x.id === waitingFor.runner_id : x.name === waitingFor.name));
        const paired = r && r.credential_state === "active" && (!waitingFor.runner_id || (r.credential && r.credential.id) !== waitingFor.credential);
        // One line step per way (the service's install line, the terminal's pair line).
        const steps = panel.querySelectorAll(".pair-line-step");
        if (paired) {
          wait.textContent = r.presence === "online" ? M.t("runners.paired.online", { name: r.name }) : M.t("runners.paired.offline", { name: r.name });
          wait.className = "ok pair-wait";
          steps.forEach((step) => append(clear(step), M.t("runners.paired.used")));
        } else if (steps.length && Date.parse(waitingFor.expires_at) <= Date.now()) {
          steps.forEach((step) => append(clear(step), M.t("runners.paired.expired")));
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
      await readLines(r.items);
      if (read !== reads) return;
      drawRunners(r.items);
      drawEnrollments(e.items);
    }

    append(root, M.pageHead({ title: M.t("runners.title"), actions: [pairOpen] }),
      h("p", { class: "muted" }, M.t("runners.intro")),
      formSlot, panel, stepSlot, status.el, pending, list);
    // Asked for (/runners/pair): open, the name focused. No runner yet: open too, as the project's
    // Agents opens its join panel without an agent of one's own; the empty state names what a
    // runner is but not how to get one (web/context/views.md). The focus stays where the page
    // puts it then: nothing was pressed.
    const asked = !!(args && args[0] === "pair");
    if (asked || !runners.items.some((r) => !r.removed_at)) openPair(false);
    await readLines(runners.items);
    drawRunners(runners.items);
    drawEnrollments(enrollments.items);
    // After the last read, so the timer runs once the router has attached the page.
    if (asked) openPair(true);
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
  M.runnerShellWord = sq;
})(window.Maity);
