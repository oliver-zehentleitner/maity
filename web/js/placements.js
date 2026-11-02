// Where the project's agents run (docs/api.md §15.5–§15.7), inside the
// Agents view: one row per placement — agent, runner, harness and model,
// what is wanted (`desired`), what the runner last reported, the
// generation — with Stop, Start and Restart for whoever may (§15.6: a
// human with members:admin who owns the runner, or the agent profile's
// owner). Stop asks nothing, it is the safe direction; a restart is
// confirmed with one more click. A placement waiting for consent links to
// its request in the inbox, which answers it. Every action is one contract
// call; a refusal is the hub's envelope as it comes. Placement events
// (§15.10) read the list again.
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

  // The section, read and drawn into the Agents view. `credentials`: the
  // agents' credentials as the view read them ({agentId: [credential]}),
  // for whether a placement's credential was revoked (§15.6 `rejoin`).
  async function section(ctx, credentials) {
    const box = h("section", { class: "placements", "aria-labelledby": "placements-title" });
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
    const runnerOwner = (p) => ctx.canAdmin && ctx.me.kind === "human" && mine.has(p.runner.id);
    // Waiting for consent, the inbox answers: a stop here would withdraw
    // the request and a restart approve it, unasked (§15.6, settling).
    const pending = (p) => !!(p.approval && (p.approval.status === "pending" || p.approval.pending_change));
    const mayAct = (p) => p.active && !pending(p) && (runnerOwner(p) || owns(p));
    // A row asking for a restart, or waiting for the hub: a redraw from an
    // event waits until it is done, so neither is wiped.
    const busy = new Set();
    const revoked = (p) => {
      const list = (p.agent && p.agent.id && credentials[p.agent.id]) || [];
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
        append(clear(list), h("li", { class: "empty muted" }, M.t("placements.empty")));
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

    let reading = null;
    async function reread() {
      if (reading) return reading;
      reading = (async () => {
        try {
          items = (await M.api.getAll(ctx.base + "/placements")).items;
          if (!busy.size) draw();
        } catch (err) {
          status.fail(M.t("placements.read_failed"), err);
        } finally {
          reading = null;
        }
      })();
      return reading;
    }

    try {
      items = (await M.api.getAll(ctx.base + "/placements")).items;
    } catch (err) {
      append(box, h("h3", { id: "placements-title" }, M.t("placements.title")), M.errorBox(err));
      return box;
    }
    draw();
    ctx.onEvents((events) => { if (events.some((e) => EVENTS.test(e.kind))) reread(); });
    append(box, h("h3", { id: "placements-title" }, M.t("placements.title")),
      h("p", { class: "muted" }, M.t("placements.hint")),
      list, status.el);
    return box;
  }

  M.placements = { section };
})(window.Maity);
