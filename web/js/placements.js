// Where the project's agents run (docs/api.md §15.5–§15.7), inside the
// Agents view: one row per placement — agent, runner, harness and model,
// what is wanted (`desired`), what the runner last reported, the
// generation — with Stop, Start and Restart for whoever may (§15.6: a
// human with members:admin who owns the runner, or the agent profile's
// owner). Stop asks nothing, it is the safe direction; a restart is
// confirmed with one more click. A placement waiting for consent links to
// its request in the inbox, which answers it. Every action is one contract
// call; a refusal is the hub's envelope as it comes. Placement events
// (§15.10) read the list again. A human with members:admin starts an agent
// on one of their own runners here too: an agent of theirs in the project
// or a new profile, with what the runner advertises (§15.6, tsk-dsp6htj4c686).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear, formatAgo, formatTime } = M.dom;

  // A placement's states and §15.7's reasons, in words from the catalog when
  // drawn; any other value is shown as it comes.
  const STATES = {
    pending: () => M.t("placements.state.pending"), starting: () => M.t("placements.state.starting"),
    running: () => M.t("placements.state.running"), stopping: () => M.t("placements.state.stopping"),
    stopped: () => M.t("placements.state.stopped"), exited: () => M.t("placements.state.exited"),
    failed: () => M.t("placements.state.failed"), rate_limited: () => M.t("placements.state.rate_limited"),
  };
  const stateWords = (x) => (Object.hasOwn(STATES, x) ? STATES[x]() : x);
  const REASONS = {
    capacity: () => M.t("placements.reason.capacity"),
    awaiting_operator: () => M.t("placements.reason.awaiting_operator"),
    harness_refused: () => M.t("placements.reason.harness_refused"),
    repository_refused: () => M.t("placements.reason.repository_refused"),
    project_refused: () => M.t("placements.reason.project_refused"),
    harness_missing: () => M.t("placements.reason.harness_missing"),
    clone_failed: () => M.t("placements.reason.clone_failed"),
    workspace_in_use: () => M.t("placements.reason.workspace_in_use"),
    join_failed: () => M.t("placements.reason.join_failed"),
    crash_loop: () => M.t("placements.reason.crash_loop"),
    quota: () => M.t("placements.reason.quota"),
    agent_credential_revoked: () => M.t("placements.reason.agent_credential_revoked"),
    oom_killed: () => M.t("placements.reason.oom_killed"), evicted: () => M.t("placements.reason.evicted"),
    image_pull: () => M.t("placements.reason.image_pull"),
    stopped_by_hub: () => M.t("placements.reason.stopped_by_hub"),
    adopted: () => M.t("placements.reason.adopted"),
    orphaned: () => M.t("placements.reason.orphaned"),
  };
  const EVENTS = /^placement_(created|updated|reported)$/;

  // What the runner says, or that it has not acted on this generation yet.
  function stateLine(ctx, p) {
    const a = p.approval || {};
    const ask = (text) => h("span", { class: "placement-consent pill pill-warn" }, text,
      a.request_id ? [" — ", h("a", { href: ctx.link("inbox", a.request_id) }, M.t("placements.consent.answer"))] : null);
    if (a.status === "pending") return ask(M.t("placements.consent.start"));
    const r = p.reported;
    const change = a.pending_change ? [" · ", ask(M.t("placements.consent.change"))] : null;
    if (!p.reported_current) {
      return h("span", { class: "placement-waiting" }, r
        ? M.t("placements.waiting.last", { generation: String(p.generation), last: stateWords(r.state) })
        : M.t("placements.waiting", { generation: String(p.generation) }), change);
    }
    const why = r.reason ? (Object.hasOwn(REASONS, r.reason) ? REASONS[r.reason]() : r.reason) : null;
    const loop = r.reason === "crash_loop" && r.crash_count
      ? M.t("placements.crash_loop", { count: r.crash_count, min: Math.round((r.crash_window_seconds || 0) / 60) }) : null;
    const bad = ["failed"].includes(r.state) || r.reason === "crash_loop";
    // A pill with a dot, so a failure stands out of the row (the
    // designer's pass part 3): running ok, failed bad, the rest grey.
    const tone = bad ? "pill-bad" : r.state === "running" ? "pill-ok" : "pill-idle";
    return h("span", { class: "placement-state pill " + tone + " state-" + r.state + (bad ? " flag-inline" : "") },
      why ? (loop ? M.t("placements.state_why_loop", { state: stateWords(r.state), why, loop }) : M.t("placements.state_why", { state: stateWords(r.state), why })) : stateWords(r.state),
      r.detail ? " · " + r.detail : "",
      r.retry_at ? [" · ", M.t("placements.again", { when: formatTime(r.retry_at) })] : "",
      " · ", M.t("placements.since", { ago: formatAgo(r.since, M.api.now()) }), change);
  }

  // A command to type on the runner's machine: its name, the command in a
  // box that scrolls sideways rather than running past the row, and Copy.
  // `words`: the command's name, its label as a region and its Copy's label.
  function command(words, text) {
    const copy = h("button", { type: "button", class: "small", "aria-label": words.copy }, M.t("placements.copy"));
    copy.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(text); copy.textContent = M.t("placements.copied"); } catch (err) { copy.textContent = M.t("placements.copy_failed"); }
      window.setTimeout(() => { copy.textContent = M.t("placements.copy"); }, 2000);
    });
    // A box that scrolls sideways is reachable by keyboard, and named.
    return h("div", { class: "placement-command" }, h("span", { class: "muted" }, words.name, ": "),
      h("code", { tabindex: "0", role: "region", "aria-label": words.region }, text), copy);
  }

  // The form that starts an agent on a runner (POST …/placements, §15.6). `runners`: the
  // attachments of one's own runners with a live credential (§15.4); `placed`: the agent ids
  // that have an active placement already, one per membership (§15.5). `made(placement)`:
  // after the hub's 201. A refusal is the hub's message and code, a field's as it names it.
  function startForm(ctx, runners, placed, hooks) {
    const words = M.runnerWords;
    const status = M.statusLine();
    const id = (x) => "placement-new-" + x;
    const field = (key, label, control, hint) => h("div", { class: "field" },
      h("label", { for: id(key) }, label), control, hint ? h("p", { class: "hint", id: id(key) + "-hint" }, hint) : null);
    const select = (key, options) => h("select", { id: id(key) }, options);
    const input = (key, attrs) => h("input", Object.assign({ id: id(key) }, attrs || {}));

    // The agent: one's own agents here without a placement, or a new profile (humans only, §15.6).
    const own = ctx.members.filter((m) => m.kind === "agent" && !m.removed_at && m.owner_id === ctx.me.id && !placed.has(m.id));
    const agent = select("agent", [h("option", { value: "" }, M.t("placements.new.agent_new"))]
      .concat(own.map((m) => h("option", { value: m.id }, m.display_name + " (@" + m.handle + ")"))));
    const handle = input("handle", { pattern: M.dom.NAME_RULES.handle.pattern, autocomplete: "off", "aria-describedby": id("handle") + "-hint" });
    const name = input("name", { autocomplete: "off" });
    // Trust admin and the role proxy only from an owner (§3.1, owner_only §2.3), as in a join.
    const trust = select("trust", (ctx.isOwner ? ["member", "guest", "admin"] : ["member", "guest"]).map((r) => h("option", { value: r }, M.trust.trustWord(r))));
    trust.value = "member";
    const role = select("role");
    const fillRoles = () => M.trust.fillRoles(role, M.trust.ROLES.filter((r) => r !== "proxy" || (ctx.isOwner && trust.value === "admin")), role.value || "coder", "coder");
    const roleHelp = M.trust.roleHint(role);
    trust.addEventListener("change", fillRoles);
    fillRoles();
    // A guest is never reported to (§2.3).
    const reportsTo = select("reports", [h("option", { value: "" }, M.t("join.reports.nobody"))]
      .concat(ctx.members.filter((x) => !x.removed_at && !M.trust.guest(x)).map((x) => h("option", { value: x.id }, x.display_name + " (@" + x.handle + ")"))));
    reportsTo.value = ctx.me.id;
    const areas = input("areas", { placeholder: "hub/, docs/" });
    const briefing = h("textarea", { id: id("briefing"), rows: "4", placeholder: M.t("join.briefing.placeholder") });
    const fresh = h("fieldset", { class: "placement-new-profile" }, h("legend", null, M.t("placements.new.profile")),
      // What a handle is, as at every other agent handle (#1488), and its rule.
      h("div", { class: "field" }, h("label", { for: id("handle") }, M.t("agents.handle")), handle,
        M.handles.explain("agent", handle), h("p", { class: "hint", id: id("handle") + "-hint" }, M.dom.NAME_RULES.handle.text)),
      field("name", M.t("agents.display_name"), name),
      field("trust", M.t("join.field.trust"), trust),
      h("div", { class: "field" }, h("label", { for: id("role") }, M.t("join.field.role")), role, roleHelp),
      field("reports", M.t("join.field.reports_to"), reportsTo),
      field("areas", M.t("join.field.areas"), areas),
      field("briefing", M.t("placements.new.briefing"), briefing));

    // The runner, and what it advertises (§15.3): where, which tool, its modes and models.
    const runner = select("runner", runners.map((a) => {
      const c = a.runner.capabilities || {};
      return h("option", { value: a.runner.id }, M.t("placements.new.runner_option", { name: a.runner.name, presence: words.presenceText(a.runner),
        running: String(c.running || 0), max: String(c.max_agents || 0) }));
    }));
    runner.value = runners[0].runner.id;
    const target = select("target");
    const tool = select("tool");
    tool.setAttribute("aria-describedby", id("tool") + "-none");
    const mode = select("mode");
    const model = select("model");
    const submit = h("button", { type: "submit", class: "primary" }, M.t("placements.new.submit"));
    const chosen = () => runners.find((a) => a.runner.id === runner.value).runner;
    const caps = () => chosen().capabilities || {};
    const tools = () => (caps().harnesses || []).filter((x) => x.available !== false && (!target.value || (x.targets || []).includes(target.value)));
    const harness = () => tools().find((x) => x.id === tool.value);
    const fillModes = () => {
      const x = harness();
      const modes = x ? x.modes || [] : [];
      append(clear(mode), modes.map((m) => h("option", { value: m }, Object.hasOwn(words.MODES, m) ? words.MODES[m] : m)));
      mode.value = x && modes.includes(x.default_mode) ? x.default_mode : modes[0] || "";
      append(clear(model), h("option", { value: "" }, M.t("placements.new.model_default")), (x ? x.models || [] : []).map((m) => h("option", { value: m }, m)));
    };
    const fillTools = () => {
      const kept = tool.value;
      const list = tools();
      append(clear(tool), list.map((x) => h("option", { value: x.id }, words.toolName(x.id) + (x.version ? " " + x.version : ""))));
      tool.value = list.some((x) => x.id === kept) ? kept : list.length ? list[0].id : "";
      noTool.hidden = !!list.length;
      // Nothing to start with: the hub would refuse it (harness_not_offered).
      submit.disabled = !list.length;
      fillModes();
    };
    const fillTargets = () => {
      append(clear(target), h("option", { value: "" }, M.t("placements.new.target_any")),
        (caps().targets || []).filter((x) => x.reachable !== false).map((x) => h("option", { value: x.name }, x.name)));
      fillTools();
    };
    const noTool = h("p", { class: "hint", id: id("tool") + "-none", hidden: true }, M.t("placements.new.no_tool"));
    runner.addEventListener("change", fillTargets);
    target.addEventListener("change", fillTools);
    tool.addEventListener("change", fillModes);

    const clone = input("clone", { pattern: "[a-z0-9][a-z0-9\\-]{0,62}", autocomplete: "off", "aria-describedby": id("clone") + "-hint" });
    const branch = input("branch", { autocomplete: "off" });
    // A reason is required while the project plans or is in review (§6.1).
    const needsReason = ["plan", "review"].includes(ctx.project.state);
    const reason = h("textarea", { id: id("reason"), rows: "2", required: needsReason || null });
    const followAgent = () => {
      // Hidden and disabled together: a disabled fieldset's controls are not validated, so a
      // handle typed before an existing agent was chosen cannot block the submit unseen.
      fresh.hidden = !!agent.value;
      fresh.disabled = !!agent.value;
      const m = own.find((x) => x.id === agent.value);
      clone.setAttribute("placeholder", m ? m.handle : handle.value.trim() || M.t("placements.new.clone_placeholder"));
    };
    agent.addEventListener("change", followAgent);
    handle.addEventListener("input", followAgent);

    const cancel = h("button", { type: "button", onclick: () => hooks.cancel() }, M.t("placements.cancel"));
    const form = h("form", { class: "placement-new", "aria-labelledby": id("title") },
      h("h4", { id: id("title") }, M.t("placements.new.title")),
      h("p", { class: "hint" }, M.t("placements.new.hint")),
      field("agent", M.t("join.field.agent"), agent), fresh,
      field("runner", M.t("placements.new.runner"), runner),
      field("target", M.t("placements.new.target"), target),
      h("div", { class: "field" }, h("label", { for: id("tool") }, M.t("placements.new.tool")), tool, noTool),
      field("mode", M.t("placements.new.mode"), mode),
      field("model", M.t("placements.new.model"), model),
      field("clone", M.t("placements.new.clone"), clone, M.t("placements.new.clone_hint")),
      field("branch", M.t("placements.new.branch"), branch),
      field("reason", needsReason ? M.t("placements.new.reason_required", { state: ctx.project.state }) : M.t("placements.new.reason"), reason),
      h("div", { class: "actions" }, submit, " ", cancel), status.el);

    // What the hub is sent: an agent by id, or a new profile with its join fields (§3.1).
    function body() {
      const b = {};
      if (agent.value) {
        b.agent = { id: agent.value };
      } else {
        b.agent = { handle: handle.value.trim(), display_name: name.value.trim() };
        b.trust = trust.value;
        b.role = role.value;
        b.reports_to = reportsTo.value || null;
        b.areas = areas.value.split(",").map((a) => a.trim()).filter(Boolean);
        b.capabilities = [];
        if (briefing.value.trim()) b.briefing = briefing.value.trim();
      }
      b.runner = runner.value;
      b.target = target.value || null;
      b.harness = tool.value;
      if (mode.value) b.mode = mode.value;
      b.model = model.value || null;
      const workspace = {};
      if (clone.value.trim()) workspace.clone = clone.value.trim();
      if (branch.value.trim()) workspace.branch = branch.value.trim();
      if (Object.keys(workspace).length) b.workspace = workspace;
      if (reason.value.trim()) b.reason = reason.value.trim();
      return b;
    }
    // A refusal as the hub sends it; the fields it names, each with its code.
    const said = (err) => {
      const fields = err.code === "invalid" && err.details && err.details.fields;
      const named = fields ? Object.entries(fields).map(([k, v]) => M.t("placements.new.field", { field: k, why: v })).join("; ") : "";
      const text = err.code ? M.t("placements.refusal", { reason: err.message || M.t("placements.an_error"), code: err.code }) : err.message || M.t("placements.an_error");
      return { message: named ? text + " — " + named : text };
    };
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (submit.disabled || !tool.value) return;
      submit.disabled = true;
      status.busy(M.t("placements.new.busy"));
      try {
        const made = await M.api.post(ctx.base + "/placements", body());
        status.done();
        await hooks.made(made);
      } catch (err) {
        status.fail(M.t("placements.new.failed"), said(err));
      } finally {
        submit.disabled = !tool.value;
      }
    });
    fillTargets();
    followAgent();
    return { form, first: agent };
  }

  // The section, read and drawn into the Agents view. `credentials`: for whether a placement's
  // credential was revoked (§15.6 `rejoin`), the agents' credentials as the view read them
  // ({agentId: [credential]}), or a function asked for the agents placed here only, once each
  // ((ids) => that map): a project with many agents and few placements reads few lists
  // (tsk-d61rvjm6gteh).
  // opts (all optional): `own` lists only the placements of one's own agents and offers no start
  // (the /agents tab, one section per project); `title` replaces the heading's words; `id` makes
  // the heading's id unique where one page holds several sections; `level` is the heading's
  // element, `h2` where the section is the page itself (the project's tab), else `h3`.
  async function section(ctx, credentials, opts) {
    opts = opts || {};
    const titleId = "placements-title" + (opts.id ? "-" + opts.id : "");
    const loads = typeof credentials === "function";
    const creds = loads ? {} : (credentials || {});
    const asked = new Set();
    const credentialsFor = async (list) => {
      if (!loads) return;
      const ids = [...new Set(list.map((p) => p.agent && p.agent.id).filter((id) => id && !asked.has(id)))];
      if (!ids.length) return;
      ids.forEach((id) => asked.add(id));
      try { Object.assign(creds, await credentials(ids)); } catch (err) { /* no rejoin offered where they are unknown */ }
    };
    const box = h("section", { class: "placements", "aria-labelledby": titleId });
    const list = h("ul", { class: "placement-list" });
    const status = M.statusLine();
    let items = [];
    // The runners this human owns: their placements are theirs to steer.
    // GET /runners also lists runners attached where one is an admin, so
    // only those whose owner one is count (placements.py _has_right).
    let mine = new Set();
    try {
      mine = new Set((await M.api.getAll("/runners")).items.filter((r) => r.owner_id === ctx.me.id).map((r) => r.id));
    } catch (err) { /* no runner of one's own known */ }
    const owns = (p) => {
      const m = p.agent && p.agent.id && ctx.memberById ? ctx.memberById[p.agent.id] : null;
      return !!m && m.owner_id === ctx.me.id;
    };
    const listed = (list) => (opts.own ? list.filter(owns) : list);
    const runnerOwner = (p) => ctx.canAdmin && ctx.me.kind === "human" && mine.has(p.runner.id);
    // Waiting for consent, the inbox answers: a stop here would withdraw
    // the request and a restart approve it, unasked (§15.6, settling).
    const pending = (p) => !!(p.approval && (p.approval.status === "pending" || p.approval.pending_change));
    const mayAct = (p) => p.active && !pending(p) && (runnerOwner(p) || owns(p));
    // A row asking for a restart, or waiting for the hub: a redraw from an
    // event waits until it is done, so neither is wiped.
    const busy = new Set();
    const revoked = (p) => {
      const list = (p.agent && p.agent.id && creds[p.agent.id]) || [];
      const c = list.find((x) => x.id === p.credential_id);
      return !!(c && c.revoked_at);
    };
    // A refusal as the hub answered it: its message and its code.
    const said = (err) => ({ message: err.code ? M.t("placements.refusal", { reason: err.message || M.t("placements.an_error"), code: err.code }) : err.message || M.t("placements.an_error") });

    // One call per row at a time: its buttons are disabled until the row
    // is drawn again; a refusal reads the list again too, as the hub has it.
    const inFlight = new Set();
    // busy and failed: the status line's words while it runs and when it is refused.
    async function act(p, busyWords, failedWords, call, row) {
      if (inFlight.has(p.id)) return;
      inFlight.add(p.id);
      busy.add(p.id);
      if (row) row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      status.busy(busyWords);
      let failed = null;
      try {
        await call();
      } catch (err) {
        failed = err;
      }
      busy.delete(p.id);
      inFlight.delete(p.id);
      await reread();
      if (failed) status.fail(failedWords, said(failed));
      else status.done();
    }
    const path = (p) => ctx.base + "/placements/" + encodeURIComponent(p.id);

    function actions(p) {
      if (!mayAct(p)) return null;
      const name = p.agent.display_name || p.agent.handle;
      const row = h("div", { class: "placement-actions" });
      const stop = h("button", { type: "button", "aria-label": M.t("placements.stop.label", { name }),
        onclick: () => act(p, M.t("placements.stopping"), M.t("placements.not_stopped"), () => M.api.patch(path(p), { desired: "stopped" }), row) }, M.t("placements.stop"));
      const start = h("button", { type: "button", "aria-label": M.t("placements.start.label", { name }),
        onclick: () => act(p, M.t("placements.starting"), M.t("placements.not_started"), () => M.api.patch(path(p), { desired: "running" }), row) }, M.t("placements.start"));
      // A restart re-runs the agent: one more click says so.
      const restartWith = (rejoin) => {
        const label = rejoin ? M.t("placements.restart_rejoin") : M.t("placements.restart");
        const b = h("button", { type: "button", "aria-label": rejoin ? M.t("placements.restart_rejoin.label", { name }) : M.t("placements.restart.label", { name }) }, label);
        b.addEventListener("click", () => {
          busy.add(p.id);
          const yes = h("button", { type: "button", class: "primary", onclick: () => act(p, M.t("placements.restarting"), M.t("placements.not_restarted"),
            () => M.api.post(path(p) + "/restart", rejoin ? { rejoin: true } : {}), row) }, rejoin ? M.t("placements.restart_rejoin.yes") : M.t("placements.restart.yes"));
          const no = h("button", { type: "button", onclick: () => { busy.delete(p.id); draw(); } }, M.t("placements.cancel"));
          append(clear(row), h("span", null, rejoin ? M.t("placements.restart_rejoin.ask", { name }) : M.t("placements.restart.ask", { name }), " "), yes, " ", no);
          yes.focus();
        });
        return b;
      };
      append(row, p.desired === "running" ? stop : start, " ", restartWith(false), revoked(p) ? [" ", restartWith(true)] : null);
      return row;
    }

    function draw() {
      if (!items.length) {
        append(clear(list), h("li", { class: "empty muted" }, opts.own ? M.t("placements.own.empty") : M.t("placements.empty")));
        return;
      }
      append(clear(list), items.map((p) => h("li", { class: "placement", "data-placement": p.id },
        h("div", { class: "placement-head" },
          p.agent.id ? M.dom.memberRef(ctx, p.agent.id) : h("span", null, p.agent.display_name),
          h("span", { class: "muted" }, " ", p.target
            ? M.tn("placements.on_target", { runner: h("strong", null, p.runner.name), target: p.target })
            : M.tn("placements.on", { runner: h("strong", null, p.runner.name) }))),
        h("dl", { class: "facts" },
          h("dt", null, M.t("placements.runs")), h("dd", null, p.harness + (p.model ? " · " + p.model : "") + " · " + p.mode),
          h("dt", null, M.t("placements.wanted")), h("dd", null, p.desired === "running" ? M.t("placements.state.running") : M.t("placements.state.stopped")),
          // The generation is for the curious: folded into the reported line, muted.
          h("dt", null, M.t("placements.reported")), h("dd", null, stateLine(ctx, p),
            h("span", { class: "muted placement-generation" }, " · ", M.t("placements.generation", { generation: String(p.generation) }),
              p.reported && p.reported.reported_at ? [" · ", M.t("placements.last_report", { ago: formatAgo(p.reported.reported_at, M.api.now()) })] : null))),
        actions(p),
        // The runner's owner sees how to look at it (§15.5: theirs only),
        // each command in a box of its own that scrolls, with Copy.
        p.session_hint || p.logs_hint ? h("div", { class: "placement-hints" },
          p.session_hint ? command({ name: M.t("placements.session"), region: M.t("placements.session.region"), copy: M.t("placements.session.copy") }, p.session_hint) : null,
          p.logs_hint ? command({ name: M.t("placements.logs"), region: M.t("placements.logs.region"), copy: M.t("placements.logs.copy") }, p.logs_hint) : null) : null)));
    }

    // One read at a time; an event that comes while one runs asks for one more after it, since that
    // read may have fetched the list before the change (web roll-up 3, after #1533's startup fix).
    let reading = null;
    let again = false;
    async function reread() {
      if (reading) { again = true; return reading; }
      reading = (async () => {
        try {
          do {
            again = false;
            items = listed((await M.api.getAll(ctx.base + "/placements")).items);
            await credentialsFor(items);
          } while (again);
          if (!busy.size) draw();
        } catch (err) {
          status.fail(M.t("placements.read_failed"), err);
        } finally {
          reading = null;
          again = false;
        }
      })();
      return reading;
    }

    // Listening before the first read (review of #1533): the project's feed hands an event to the
    // listeners there are when it comes, so one that comes while the placements or their credentials
    // are read would be lost. It is kept, and the list read again once the section stands.
    let loaded = false;
    let missed = false;
    ctx.onEvents((events) => {
      if (!events.some((e) => EVENTS.test(e.kind))) return;
      if (loaded) reread(); else missed = true;
    });
    const heading = () => h(opts.level || "h3", { id: titleId }, opts.title || M.t("placements.title"));
    try {
      items = listed((await M.api.getAll(ctx.base + "/placements")).items);
    } catch (err) {
      append(box, heading(), M.errorBox(err));
      return box;
    }
    await credentialsFor(items);
    draw();
    loaded = true;
    if (missed) reread();
    append(box, heading(),
      opts.own ? null : h("p", { class: "muted" }, M.t("placements.hint")),
      opts.own ? null : await starting(), list, status.el);
    return box;

    // Start on a runner: for a human with members:admin, over the runners of their own that
    // are attached here with a live credential (§15.4, §15.6) and offer this project's
    // repository (the hub's `repository_not_offered`); none, and the way to allow one.
    async function starting() {
      if (!ctx.canAdmin || ctx.me.kind !== "human") return null;
      // A project without a repository: the hub refuses every placement, so no form.
      const repo = ctx.project && ctx.project.repository && ctx.project.repository.url;
      if (!repo) return h("p", { class: "hint placement-new-none" }, M.t("placements.new.no_repository"));
      let runners = [];
      try {
        runners = (await M.api.getAll(ctx.base + "/runners")).items
          .filter((a) => a.runner.owner_id === ctx.me.id && a.runner.credential_state === "active" && !a.runner.removed_at);
      } catch (err) {
        return h("p", { class: "send-status failed" }, M.t("placements.new.runners_failed", { reason: err.message }));
      }
      if (!runners.length) {
        return h("p", { class: "hint placement-new-none" }, M.tn("placements.new.none",
          { link: h("a", { href: ctx.link("runners") }, M.t("placements.new.none_link")) }));
      }
      const name = repositoryName(repo);
      runners = runners.filter((a) => ((a.runner.capabilities || {}).repositories || []).some((p) => typeof p === "string" && fnmatch(name, p)));
      if (!runners.length) {
        return h("p", { class: "hint placement-new-none" }, M.tn("placements.new.no_runner_offers", { repository: h("code", null, name) }));
      }
      const slot = h("div", { class: "placement-new-slot" });
      const open = h("button", { type: "button", class: "placement-new-open", "aria-expanded": "false" }, M.t("placements.new.open"));
      const close = (refocus) => {
        clear(slot);
        open.hidden = false;
        open.setAttribute("aria-expanded", "false");
        if (refocus) open.focus();
      };
      open.addEventListener("click", () => {
        const placed = new Set(items.filter((p) => p.active && p.agent.id).map((p) => p.agent.id));
        const f = startForm(ctx, runners, placed, {
          cancel: () => close(true),
          // Only the form that sent it closes: one cancelled while its POST ran and opened anew
          // keeps its draft and the focus; the placement made is listed and said all the same.
          made: async (made) => {
            const mine = f.form.parentNode === slot;
            if (mine) close(false);
            await reread();
            append(clear(status.el), h("span", { class: "ok" }, M.t("placements.new.done",
              { name: made.agent.display_name || made.agent.handle, runner: made.runner.name })));
            if (mine) status.el.focus();
          },
        });
        append(clear(slot), f.form);
        open.hidden = true;
        open.setAttribute("aria-expanded", "true");
        f.first.focus();
      });
      status.el.setAttribute("tabindex", "-1");
      return h("div", { class: "placement-new-box" }, open, slot);
    }
  }

  // The repository as a runner names it, and the hub's match of it against a runner's advertised
  // patterns (`check_repository` in hub/src/maity_hub/placements.py: the URL without `https://`
  // and trailing slashes, Python's `fnmatch.fnmatchcase`: `*` and `?` across `/` too, `[…]` and
  // `[!…]` a set, case kept). A set is read as Python 3.12's `fnmatch.translate` reads it: split
  // at the hyphens that make ranges, a reversed range dropped, so `[z-a]` matches nothing and
  // `[!z-a]` any one character, never a set JS cannot compile. The name is read by Unicode code
  // point, as Python counts characters: `?` takes a character beyond U+FFFF whole, not half of it.
  // An advertised pattern is printable ASCII on the hub; the port reads any pattern the same way.
  const repositoryName = (url) => url.replace(/^https:\/\//, "").replace(/\/+$/, "");
  const inSet = (s) => s.replace(/[\\\]\[^-]/g, "\\$&");
  function charSet(pattern, i, j) {
    const at = (a, b) => pattern.slice(a, b).join("");
    let chunks;
    if (!pattern.slice(i, j).includes("-")) chunks = [at(i, j)];
    else {
      chunks = [];
      let k = pattern[i] === "!" ? i + 2 : i + 1;
      for (;;) {
        k = pattern.indexOf("-", k);
        if (k < 0 || k >= j) break;
        chunks.push(at(i, k));
        i = k + 1;
        k = k + 3;
      }
      const chunk = at(i, j);
      if (chunk) chunks.push(chunk);
      else chunks[chunks.length - 1] += "-";
      for (let k = chunks.length - 1; k > 0; k--) {
        const last = Array.from(chunks[k - 1]), next = Array.from(chunks[k]);
        if (last[last.length - 1].codePointAt(0) > next[0].codePointAt(0)) {
          chunks[k - 1] = last.slice(0, -1).join("") + next.slice(1).join("");
          chunks.splice(k, 1);
        }
      }
    }
    const stuff = chunks.join("-");
    if (!stuff) return "(?!)";
    if (stuff === "!") return "[\\s\\S]";
    const not = stuff[0] === "!";
    if (not) chunks[0] = chunks[0].slice(1);
    return "[" + (not ? "^" : "") + chunks.map(inSet).join("-") + "]";
  }
  // Each `*` is matched by going back only to the last `*` seen, never by a RegExp over the whole
  // pattern: a pattern of many stars against a long name stays linear in each, as on the hub
  // (4hv7 at #1567), where a backtracking RegExp took seconds. A set is tested as one character.
  const STAR = {};
  function fnmatch(name, text) {
    const pattern = Array.from(text);
    const n = pattern.length;
    const tokens = [];
    let i = 0;
    while (i < n) {
      const c = pattern[i++];
      if (c === "*") {
        if (tokens[tokens.length - 1] !== STAR) tokens.push(STAR);
      } else if (c === "?") tokens.push(() => true);
      else if (c === "[") {
        let j = i;
        if (j < n && pattern[j] === "!") j++;
        if (j < n && pattern[j] === "]") j++;
        while (j < n && pattern[j] !== "]") j++;
        if (j >= n) tokens.push((x) => x === "[");
        else {
          let one;
          try {
            one = new RegExp("^" + charSet(pattern, i, j) + "$", "u");
          } catch (e) {
            return false; // a set this port cannot read is no match; the other patterns still count
          }
          tokens.push((x) => one.test(x));
          i = j + 1;
        }
      } else tokens.push((x) => x === c);
    }
    const chars = Array.from(name);
    let p = 0, at = 0, star = -1, mark = 0;
    while (at < chars.length) {
      if (p < tokens.length && tokens[p] !== STAR && tokens[p](chars[at])) {
        p++;
        at++;
      } else if (p < tokens.length && tokens[p] === STAR) {
        star = p++;
        mark = at;
      } else if (star >= 0) {
        p = star + 1;
        at = ++mark;
      } else return false;
    }
    while (p < tokens.length && tokens[p] === STAR) p++;
    return p === tokens.length;
  }

  M.placements = { section, fnmatch };
})(window.Maity);
