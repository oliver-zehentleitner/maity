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

  const STATES = {
    pending: "pending", starting: "starting", running: "running", stopping: "stopping",
    stopped: "stopped", exited: "exited", failed: "failed", rate_limited: "rate limited",
  };
  // §15.7's reasons, in words; any other code is shown as it comes.
  const REASONS = {
    capacity: "the runner is at its agent limit",
    awaiting_operator: "waits for the operator on the runner host",
    harness_refused: "the runner's configuration does not allow this harness, mode or model",
    repository_refused: "the repository is not in the runner's allowlist",
    project_refused: "the project is not in the runner's allowlist",
    harness_missing: "the harness is not installed on the runner",
    clone_failed: "git clone failed",
    workspace_in_use: "the clone belongs to someone else",
    join_failed: "joining failed",
    crash_loop: "crash loop",
    quota: "the harness's quota",
    agent_credential_revoked: "the agent's credential was revoked",
    oom_killed: "out of memory", evicted: "evicted", image_pull: "the image could not be pulled",
    stopped_by_hub: "stopped as asked",
    adopted: "taken over after the runner restarted",
    orphaned: "ended: no placement for it",
  };
  const EVENTS = /^placement_(created|updated|reported)$/;

  // What the runner says, or that it has not acted on this generation yet.
  function stateLine(ctx, p) {
    const a = p.approval || {};
    const ask = (text) => h("span", { class: "placement-consent" }, text,
      a.request_id ? [" — ", h("a", { href: ctx.link("inbox", a.request_id) }, "answer it in the inbox")] : null);
    if (a.status === "pending") return ask("Waits for consent to start");
    const r = p.reported;
    const change = a.pending_change ? [" · ", ask("a change waits for consent")] : null;
    if (!p.reported_current) {
      return h("span", { class: "placement-waiting" }, "Waiting for the runner to act on generation " + p.generation
        + (r ? " (last: " + (STATES[r.state] || r.state) + ")" : ""), change);
    }
    const why = r.reason ? REASONS[r.reason] || r.reason : null;
    const loop = r.reason === "crash_loop" && r.crash_count
      ? " (" + r.crash_count + " quick exits within " + Math.round((r.crash_window_seconds || 0) / 60) + " min)" : "";
    const bad = ["failed"].includes(r.state) || r.reason === "crash_loop";
    return h("span", { class: "placement-state state-" + r.state + (bad ? " flag-inline" : "") },
      (STATES[r.state] || r.state) + (why ? ": " + why + loop : "") + (r.detail ? " · " + r.detail : ""),
      r.retry_at ? " · again " + formatTime(r.retry_at) : "",
      " · since " + formatAgo(r.since, M.api.now()), change);
  }

  // The section, read and drawn into the Agents view. `credentials`: the
  // agents' credentials as the view read them ({agentId: [credential]}),
  // for whether a placement's credential was revoked (§15.6 `rejoin`).
  async function section(ctx, credentials) {
    let served = false;
    try { served = await M.api.hubHas("GET", "/projects/{slug}/placements"); } catch (err) { served = false; }
    if (!served) return null;
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
    const said = (err) => ({ message: (err.message || "an error") + (err.code ? " (" + err.code + ")" : "") });

    // One call per row at a time: its buttons are disabled until the row
    // is drawn again; a refusal reads the list again too, as the hub has it.
    const inFlight = new Set();
    async function act(p, verb, call, row) {
      if (inFlight.has(p.id)) return;
      inFlight.add(p.id);
      busy.add(p.id);
      if (row) row.querySelectorAll("button").forEach((b) => { b.disabled = true; });
      status.busy(verb + "…");
      let failed = null;
      try {
        await call();
      } catch (err) {
        failed = err;
      }
      busy.delete(p.id);
      inFlight.delete(p.id);
      await reread();
      if (failed) status.fail("Not " + verb.toLowerCase() + ": ", said(failed));
      else status.done();
    }
    const path = (p) => ctx.base + "/placements/" + encodeURIComponent(p.id);

    function actions(p) {
      if (!mayAct(p)) return null;
      const name = p.agent.display_name || p.agent.handle;
      const row = h("div", { class: "placement-actions" });
      const stop = h("button", { type: "button", "aria-label": "Stop " + name,
        onclick: () => act(p, "Stopped", () => M.api.patch(path(p), { desired: "stopped" }), row) }, "Stop");
      const start = h("button", { type: "button", "aria-label": "Start " + name,
        onclick: () => act(p, "Started", () => M.api.patch(path(p), { desired: "running" }), row) }, "Start");
      // A restart re-runs the agent: one more click says so.
      const restartWith = (rejoin) => {
        const label = rejoin ? "Restart with a new join" : "Restart";
        const b = h("button", { type: "button", "aria-label": label + " " + name }, label);
        b.addEventListener("click", () => {
          busy.add(p.id);
          const yes = h("button", { type: "button", class: "primary", onclick: () => act(p, "Restarted",
            () => M.api.post(path(p) + "/restart", rejoin ? { rejoin: true } : {}), row) }, "Yes, " + label.toLowerCase());
          const no = h("button", { type: "button", onclick: () => { busy.delete(p.id); draw(); } }, "Cancel");
          append(clear(row), h("span", null, (rejoin ? "Restart " + name + " with a new credential?" : "Restart " + name + "? Its session ends and starts again.") + " "), yes, " ", no);
          yes.focus();
        });
        return b;
      };
      append(row, p.desired === "running" ? stop : start, " ", restartWith(false), revoked(p) ? [" ", restartWith(true)] : null);
      return row;
    }

    function draw() {
      if (!items.length) {
        append(clear(list), h("li", { class: "empty muted" }, "No agent of this project runs on a runner. A runner's owner places one from the Runners view."));
        return;
      }
      append(clear(list), items.map((p) => h("li", { class: "placement", "data-placement": p.id },
        h("div", { class: "placement-head" },
          p.agent.id ? M.dom.memberRef(ctx, p.agent.id) : h("span", null, p.agent.display_name),
          h("span", { class: "muted" }, " on ", h("strong", null, p.runner.name), p.target ? " (" + p.target + ")" : "")),
        h("dl", { class: "facts" },
          h("dt", null, "Runs"), h("dd", null, p.harness + (p.model ? " · " + p.model : "") + " · " + p.mode),
          h("dt", null, "Wanted"), h("dd", null, p.desired === "running" ? "running" : "stopped"),
          h("dt", null, "Reported"), h("dd", null, stateLine(ctx, p)),
          h("dt", null, "Generation"), h("dd", null, String(p.generation),
            p.reported && p.reported.reported_at ? " · last report " + formatAgo(p.reported.reported_at, M.api.now()) : "")),
        actions(p),
        // The runner's owner sees how to look at it (§15.5: theirs only).
        p.session_hint || p.logs_hint ? h("p", { class: "hint placement-hints" },
          p.session_hint ? ["Session: ", h("code", null, p.session_hint)] : null,
          p.session_hint && p.logs_hint ? " · " : null,
          p.logs_hint ? ["Logs: ", h("code", null, p.logs_hint)] : null) : null)));
    }

    let reading = null;
    async function reread() {
      if (reading) return reading;
      reading = (async () => {
        try {
          items = (await M.api.getAll(ctx.base + "/placements")).items;
          if (!busy.size) draw();
        } catch (err) {
          status.fail("The placements could not be read: ", err);
        } finally {
          reading = null;
        }
      })();
      return reading;
    }

    try {
      items = (await M.api.getAll(ctx.base + "/placements")).items;
    } catch (err) {
      append(box, h("h3", { id: "placements-title" }, "Where they run"), M.errorBox(err));
      return box;
    }
    draw();
    ctx.onEvents((events) => { if (events.some((e) => EVENTS.test(e.kind))) reread(); });
    append(box, h("h3", { id: "placements-title" }, "Where they run"),
      h("p", { class: "muted" }, "Agents a runner starts for this project: what is wanted, and what the runner last reported."),
      list, status.el);
    return box;
  }

  M.placements = { section };
})(window.Maity);
