// (8) Runners (#/runners): the small services on the operator's own
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
  const NAME_RULE = M.dom.NAME_RULES.handle.text;
  // The CLI as published on PyPI; the runner commands are part of it.
  const CLI_INSTALL = "pipx install maity";
  const CONFIG_PATH = "~/.config/maity-runner/runner.toml";

  // ---- plain words for what a runner advertises (shared with Project → Runners)

  const TOOLS = {
    "claude-code": "Claude Code", codex: "Codex", opencode: "opencode", pi: "pi", hermes: "Hermes",
    kimi: "Kimi Code", cline: "Cline", omp: "oh-my-pi", stub: "a test tool",
  };
  const toolName = (id) => TOOLS[id] || id;
  const MODES = {
    interactive: "a session you can attach to (tmux)",
    supervised: "woken by events, no open session (no tokens while idle)",
  };

  // local: one machine; ssh: hosts; k8s: a pool of pods.
  function backendLabel(runner) {
    const c = runner.capabilities;
    if (!c) return "has not reported what it can do yet";
    const targets = (c.targets || []).map((t) => t.name);
    if (c.backend === "local") return "this machine";
    if (c.backend === "ssh") return "hosts " + targets.join(", ");
    if (c.backend === "k8s") return "pods in " + targets.join(", ");
    return c.backend;
  }

  function presenceText(runner) {
    if (runner.removed_at) return "removed " + formatAgo(runner.removed_at);
    if (runner.credential_state === "revoked") return "revoked";
    if (runner.credential_state === "none") return "not paired yet";
    if (runner.presence === "online") return "online";
    const seen = runner.last_seen_at ? ", last seen " + formatAgo(runner.last_seen_at) : ", never connected";
    return (runner.presence === "away" ? "away" : "offline") + seen;
  }

  const presenceClass = (runner) => (runner.credential_state !== "active" || runner.removed_at ? "revoked" : (runner.presence || "offline"));

  // "Agents on this machine run as user oliver, with the runner, together."
  function isolationSentence(runner, target) {
    const where = runner.capabilities.backend === "local" ? "on " + runner.name : "on " + target.name;
    const iso = target.isolation || {};
    if (iso.kind === "shared_user") {
      return "Agents " + where + " run as one user, " + (iso.user || "?") + ", and can see each other's files"
        + (iso.runner_separate ? "; the runner itself runs as another user." : ", as the runner itself does.");
    }
    if (iso.kind === "own_user") return "Each agent " + where + " runs as its own user and cannot see the others' files.";
    if (iso.kind === "pod") return "Each agent " + where + " runs in its own pod, with its own storage.";
    return "How agents " + where + " are kept apart is not reported (" + (iso.kind || "unknown") + ").";
  }

  function targetLine(runner, target) {
    const c = runner.capabilities;
    const label = c.backend === "local" ? "" : (c.backend === "ssh" ? "host " : "pool ") + target.name + ": ";
    return label + target.running + " of " + target.max_agents + " agents running"
      + (target.reachable === false ? " · unreachable" + (target.unreachable_since ? " since " + formatAgo(target.unreachable_since) : "") : "");
  }

  function toolLine(runner, tool) {
    if (tool.available === false) {
      const why = tool.reason === "binary_not_found" ? "is not installed on " + runner.name
        : tool.reason === "version_failed" ? "did not report its version on " + runner.name : (tool.reason || "is not available");
      return h("li", { class: "unavailable" }, toolName(tool.id) + " " + why);
    }
    const bounds = tool.confinement === "allowlist" ? "kept to its command allowlist"
      : tool.confinement === "pod" ? "without a command allowlist: its pod is the only boundary"
        : tool.confinement === "none" ? "for tests only" : tool.confinement;
    return h("li", null, h("strong", null, toolName(tool.id)), (tool.version ? " " + tool.version : "") + " · " + bounds
      + (tool.sandbox === "on" ? ", in its OS sandbox" : "")
      + " · " + (tool.modes || []).map((m) => MODES[m] || m).join("; or ")
      + ((tool.models || []).length ? " · models " + tool.models.join(", ") : ""));
  }

  // What a runner can do, in words: hosts or pools, tools, how agents are kept apart.
  function capabilities(runner) {
    const c = runner.capabilities;
    if (!c) return h("p", { class: "muted" }, "It has not reported what it can do yet; it does when it connects.");
    return h("div", { class: "runner-caps" },
      h("ul", { class: "runner-targets" }, (c.targets || []).map((t) => h("li", null, targetLine(runner, t)))),
      h("h4", null, "Tools"),
      (c.harnesses || []).length ? h("ul", { class: "runner-tools" }, c.harnesses.map((t) => toolLine(runner, t)))
        : h("p", { class: "muted" }, "None configured."),
      h("h4", null, "Who can see what"),
      h("ul", { class: "runner-isolation" }, (c.targets || []).map((t) => h("li", null, isolationSentence(runner, t)))),
      h("p", { class: "muted" }, "Its configuration allows the projects " + ((c.projects || []).join(", ") || "none")
        + " and the repositories " + ((c.repositories || []).join(", ") || "none")
        + (c.require_local_approval ? "; every new agent waits for approval on that machine." : ".")));
  }

  M.runnerWords = { toolName, backendLabel, presenceText, presenceClass, capabilities, isolationSentence, MODES };

  // ---- the starter configuration --------------------------------------------

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
          b.textContent = "Copied";
        } catch (err) {
          b.textContent = "Copy failed — select the text";
        }
      },
    }, label || "Copy");
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
      h("p", null, h("strong", null, "On the machine that should run agents, in a terminal there (not in an agent session):")),
      h("ol", null,
        h("li", null, "Install the Maity CLI:", h("pre", { class: "paste-line" }, CLI_INSTALL), copyButton(() => CLI_INSTALL),
          h("p", { class: "hint" }, "This installs the published CLI, which brings maity runner pair, check, serve and stop-all.")),
        config
          ? h("li", null, "Save this configuration as " + CONFIG_PATH + ". It allows the projects you chose and their repositories, "
            + "and one tool, Claude Code; change it as you like.",
          h("pre", { class: "runner-config", tabindex: "0", "aria-label": "Starter configuration" }, config),
          copyButton(() => config, "Copy the configuration"), " ", copyButton(() => heredoc, "Copy as a command that writes the file"))
          : h("li", null, "Keep your existing configuration."),
        h("li", { class: "pair-line-step" }, "Pair it. This line is shown once and expires " + formatTime(enrollment.expires_at) + ":",
          h("pre", { class: "paste-line" }, enrollment.pair_line), copyButton(() => enrollment.pair_line)),
        h("li", null, "Check it: ", h("code", null, "maity runner check"), " says what is still missing, such as the tool's login."),
        h("li", null, "Start it: ", h("code", null, "maity runner serve"), ".")),
      h("p", { class: "muted pair-wait" }, "Waiting for the runner to pair…"),
      h("div", { class: "actions" }, h("button", { type: "button", onclick: onHide }, "Hide")));
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
      append(pending, h("h3", null, "Open pairings"), h("ul", { class: "joins" }, open.map((e) => h("li", null,
        h("code", null, e.id), " " + (e.name || "re-pair of " + e.runner_id) + " · expires " + formatTime(e.expires_at),
        h("button", {
          type: "button",
          class: "danger",
          onclick: async () => {
            status.busy("Revoking…");
            try {
              await M.api.del("/runners/enrollments/" + encodeURIComponent(e.id));
              drawEnrollments((await M.api.getAll("/runners/enrollments")).items);
              status.done();
            } catch (err) {
              status.fail("Not revoked: ", err);
            }
          },
        }, "Revoke")))));
    }

    async function act(label, call, after) {
      status.busy(label + "…");
      try {
        const answer = await call();
        status.done();
        if (after) after(answer);
        await reload();
      } catch (err) {
        status.fail(label + " failed: ", err);
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
          if (!NAME.test(name)) { status.fail("Not renamed: ", { message: NAME_RULE }); return; }
          if (name === r.name) return;
          act("Renaming", () => M.api.patch("/runners/" + encodeURIComponent(r.id), { name }));
        },
      }, h("label", { for: id }, "Name"), nameInput, h("button", { type: "submit", class: "small" }, "Rename"));
      const cred = r.credential;
      return h("article", { class: "runner", "aria-label": r.name },
        h("header", null,
          h("span", { class: "dot " + presenceClass(r) }),
          h("h3", null, r.name),
          h("span", { class: "presence " + presenceClass(r) }, presenceText(r)),
          h("span", { class: "muted" }, " · " + backendLabel(r) + (r.version ? " · " + r.version : ""))),
        r.projects && r.projects.length
          ? h("p", null, "Allowed in " + r.projects.join(", ") + ".")
          : h("p", { class: "muted" }, "Not allowed in any project yet; allow it in a project's Runners tab."),
        capabilities(r),
        cred
          ? h("p", { class: "muted" }, "Credential ", h("code", null, cred.id), " · created " + formatTime(cred.created_at)
            + (cred.last_used_at ? " · last used " + formatAgo(cred.last_used_at) : "")
            + (cred.revoked_at ? " · revoked " + formatTime(cred.revoked_at) + (cred.revoked_reason ? " (" + cred.revoked_reason + ")" : "") : ""))
          : null,
        h("div", { class: "runner-actions" },
          rename,
          h("button", {
            type: "button",
            onclick: () => act("Creating a new pairing line", () => M.api.post("/runners/enrollments", { runner_id: r.id }),
              (e) => showPairing(e, null, { runner_id: r.id, name: r.name, expires_at: e.expires_at, credential: cred && cred.id })),
          }, "Re-pair"),
          r.credential_state === "active"
            ? h("button", {
              type: "button",
              class: "danger separated",
              onclick: () => {
                if (!window.confirm("Revoke " + r.name + "'s credential? It stops talking to the hub at once; its agents keep running until you stop them.")) return;
                act("Revoking", () => M.api.post("/runners/" + encodeURIComponent(r.id) + "/revoke", {}));
              },
            }, "Revoke")
            : null,
          h("button", {
            type: "button",
            class: "danger" + (r.credential_state === "active" ? "" : " separated"),
            onclick: () => {
              if (!window.confirm("Remove " + r.name + "? Its credential is revoked, it leaves every project and the hub closes its placements; "
                + "agents still running on that machine are yours to stop there (maity runner stop-all).")) return;
              act("Removing", () => M.api.del("/runners/" + encodeURIComponent(r.id)), showRemoved);
            },
          }, "Remove")));
    }

    function showRemoved(answer) {
      const still = answer.still_running || [];
      clear(panel);
      append(panel, h("div", { class: "flag", role: "status" },
        h("p", null, h("strong", null, answer.name + " was removed.")),
        still.length
          ? [h("p", null, "These agents were still running on it. The hub no longer talks to it, so ending them is yours, on that machine: ",
            h("code", null, "maity runner stop-all"), "."),
          h("ul", null, still.map((p) => h("li", null, (p.agent && (p.agent.display_name || p.agent.handle)) || p.id,
            p.reported ? " · " + p.reported.state : "")))]
          : h("p", null, "Nothing was running on it."),
        h("div", { class: "actions" }, h("button", { type: "button", onclick: () => clear(panel) }, "Hide"))));
    }

    function showPairing(enrollment, config, waiting, note) {
      waitingFor = waiting;
      clear(panel);
      if (note) append(panel, h("p", { class: "flag" }, note));
      append(panel, pairSteps(enrollment, config, () => { waitingFor = null; clear(panel); }));
    }

    function pairForm() {
      const name = h("input", { id: "pair-name", required: true, pattern: NAME_PATTERN, maxlength: "31", placeholder: "e.g. home-laptop",
        autocomplete: "off", spellcheck: "false", "aria-describedby": "pair-name-rule" });
      const ttl = h("select", { id: "pair-ttl" },
        [[900, "15 minutes"], [600, "10 minutes"], [300, "5 minutes"]].map(([v, l]) => h("option", { value: String(v) }, l)));
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
          if (!NAME.test(n)) { status.fail("No pairing line: ", { message: "the name: " + NAME_RULE }); name.focus(); return; }
          const attach = boxes.filter((b) => b.box.checked).map((b) => b.p.full_name);
          const chosen = adminProjects.filter((p) => attach.includes(p.full_name));
          // A hub before attachments (docs/api.md §15.4) refuses `attach`: pair
          // without it, and say where the runner is allowed instead.
          let note = null;
          const create = () => M.api.post("/runners/enrollments", { name: n, ttl_seconds: Number(ttl.value), attach })
            .catch((err) => {
              const f = err.code === "invalid" && err.details && err.details.fields;
              if (!attach.length || !f || f.attach !== "not_supported_yet") throw err;
              note = "This hub cannot allow the runner in projects while pairing yet; allow it in each project's Runners tab once it can.";
              return M.api.post("/runners/enrollments", { name: n, ttl_seconds: Number(ttl.value) });
            });
          act("Creating the pairing line", create,
            (enr) => showPairing(enr, starterConfig(new URL(enr.pair_url).origin, chosen), { name: n, expires_at: enr.expires_at }, note));
        },
      },
      h("h3", null, "Pair a runner"),
      h("p", { class: "hint" }, "A runner is a small service on one of your machines that starts agents for you, in the projects you allow. "
        + "The hub never starts anything itself."),
      h("label", { for: "pair-name" }, "Name of the machine's runner"), name, h("p", { class: "hint", id: "pair-name-rule" }, NAME_RULE),
      boxes.length ? h("fieldset", { class: "pair-projects" }, h("legend", null, "Allow it in"),
        boxes.map(({ p, box }) => h("label", { class: "check", for: box.id }, box, " " + p.name))) : null,
      h("label", { for: "pair-ttl" }, "The pairing line is valid for"), ttl,
      h("button", { type: "submit" }, "Create the pairing line"));
    }

    function drawRunners(items) {
      clear(list);
      const live = items.filter((r) => !r.removed_at);
      if (!live.length) {
        append(list, h("div", { class: "empty-state" }, h("p", null, "No runner yet. A runner is a small service on your machine that starts agents for you.")));
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
          wait.textContent = r.presence === "online" ? r.name + " is online." : r.name + " is paired; it shows online once maity runner serve runs.";
          wait.className = "ok pair-wait";
          if (step) append(clear(step), "Paired; the line is used up.");
        } else if (step && Date.parse(waitingFor.expires_at) <= Date.now()) {
          append(clear(step), "The line expired unused; create a new one.");
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

    append(root, h("h2", null, "Runners"),
      h("p", { class: "muted" }, "Runners start agents on your machines, ssh hosts or a cluster, only for the projects and repositories their own configuration allows."),
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
        status.fail("Could not refresh: ", err);
      } finally {
        polling = false;
      }
    });
  };

  M.runnerStarterConfig = starterConfig;
  M.runnerConfigCommand = writeCommand;
})(window.Maity);
