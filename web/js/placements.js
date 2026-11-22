// Where the project's agents run (docs/api.md §15.5–§15.7), inside the
// Agents view: one row per placement — agent, runner, harness and model,
// what is wanted (`desired`), what the runner last reported, the
// generation — with Stop for the runner's owner and the agent profile's
// owner, Start and Restart for the runner's side only (§15.6: the runner's
// owner, with members:admin or as the profile's owner) — Reset beside Restart, a
// restart on a fresh harness session (`fresh_session`) — and Remove for the
// runner's owner and the profile's owner, an own placement as much as a
// `foreign` one (DELETE, §15.6; tsk-44x5grp6fcsq). Stop
// asks nothing, it is the safe direction; a restart and a reset are confirmed
// with one more click. A placement waiting for consent links to
// its request in the inbox, which answers it. Every action is one contract
// call; a refusal is the hub's envelope as it comes. Placement events
// (§15.10) read the list again. Starting an agent on one of one's own
// runners is the runner part of the one Join an agent form (`runnerPart`,
// js/join.js; §15.6, tsk-dsp6htj4c686, tsk-hdczmsq2r431).
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
    hung: () => M.t("placements.reason.hung"),
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
    // The agent profile's owner. A placement that admits a profile that is not a member yet
    // (§15.6) runs no membership to name the owner until its first pickup; only that profile's
    // owner creates such a placement, so its creator is the owner (§15.5 `created_by`).
    const owns = (p) => {
      const id = p.agent && p.agent.id;
      const m = id && ctx.memberById ? ctx.memberById[id] : null;
      if (m) return m.owner_id === ctx.me.id;
      return !!id && !p.proposed_by && p.created_by === ctx.me.id;
    };
    const listed = (list) => (opts.own ? list.filter(owns) : list);
    // `logs_hint` reaches the runner's owner only (§15.5): the hub's own word on it.
    const ownsRunner = (p) => ctx.me.kind === "human" && (mine.has(p.runner.id) || !!p.logs_hint);
    // Start and restart: the runner's side only (runner_owner_only, §15.6).
    const mayStart = (p) => ownsRunner(p) && (ctx.canAdmin || owns(p));
    // Waiting for consent, the inbox answers: a stop here would withdraw
    // the request and a restart approve it, unasked (§15.6, settling).
    const pending = (p) => !!(p.approval && (p.approval.status === "pending" || p.approval.pending_change));
    const mayAct = (p) => p.active && !pending(p) && (ownsRunner(p) || owns(p));
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
      // A restart re-runs the agent: one more click says so. A new join is a restart
      // with `rejoin`, a reset one with `fresh_session` (§15.6): the agent starts on a fresh
      // harness session instead of resuming the last one, the clone and its branches kept.
      // Each with its words: the button, its label, the question, the yes, and the status line's.
      const RESTARTS = {
        restart: { body: {}, button: () => M.t("placements.restart"), label: (v) => M.t("placements.restart.label", v),
          ask: (v) => M.t("placements.restart.ask", v), yes: () => M.t("placements.restart.yes"),
          busy: () => M.t("placements.restarting"), failed: () => M.t("placements.not_restarted") },
        rejoin: { body: { rejoin: true }, button: () => M.t("placements.restart_rejoin"), label: (v) => M.t("placements.restart_rejoin.label", v),
          ask: (v) => M.t("placements.restart_rejoin.ask", v), yes: () => M.t("placements.restart_rejoin.yes"),
          busy: () => M.t("placements.restarting"), failed: () => M.t("placements.not_restarted") },
        reset: { body: { fresh_session: true }, button: () => M.t("placements.reset"), label: (v) => M.t("placements.reset.label", v),
          ask: (v) => M.t("placements.reset.ask", v), yes: () => M.t("placements.reset.yes"),
          busy: () => M.t("placements.resetting"), failed: () => M.t("placements.not_reset") },
      };
      const restartWith = (kind) => {
        const k = RESTARTS[kind];
        const b = h("button", { type: "button", "aria-label": k.label({ name }) }, k.button());
        b.addEventListener("click", () => {
          busy.add(p.id);
          const yes = h("button", { type: "button", class: "primary", onclick: () => act(p, k.busy(), k.failed(),
            () => M.api.post(path(p) + "/restart", k.body), row) }, k.yes());
          const no = h("button", { type: "button", onclick: () => { busy.delete(p.id); draw(); } }, M.t("placements.cancel"));
          append(clear(row), h("span", null, k.ask({ name }), " "), yes, " ", no);
          yes.focus();
        });
        return b;
      };
      // Ended by the runner's owner or the profile's owner, who places it again on a
      // runner of their own (§15.5, §15.14): its instance stops counting toward the agent's
      // max_instances, which the start form (`runnerPart`) counts, once its credential is
      // revoked. Whoever may act on a row here may delete it (§15.6 DELETE: the runner's
      // owner with any trust, members:admin with the runner included, or the profile's
      // owner): `mayAct` above.
      const remove = h("button", { type: "button", class: "danger", "aria-label": M.t("placements.remove.label", { name }),
        onclick: () => {
          if (!window.confirm(M.t("placements.remove.ask", { name }))) return;
          act(p, M.t("placements.removing"), M.t("placements.not_removed"), () => M.api.del(path(p)), row);
        } }, M.t("placements.remove"));
      const starts = mayStart(p);
      append(row, p.desired === "running" ? stop : starts ? start : null,
        starts ? [" ", restartWith("restart"), " ", restartWith("reset"), revoked(p) ? [" ", restartWith("rejoin")] : null] : null,
        " ", remove);
      return row;
    }

    function draw() {
      if (!items.length) {
        append(clear(list), h("li", { class: "empty muted" }, opts.own ? M.t("placements.own.empty") : M.t("placements.empty")));
        return;
      }
      append(clear(list), items.map((p) => h("li", { class: "placement", "data-placement": p.id },
        h("div", { class: "placement-head" },
          // The object, not the id: before its first pickup a profile is no member here and is
          // named by the placement's display_name, not its id (review A1878 of #2085).
          p.agent.id ? M.dom.memberRef(ctx, p.agent) : h("span", null, p.agent.display_name),
          h("span", { class: "muted" }, " ", p.target
            ? M.tn("placements.on_target", { runner: h("strong", null, p.runner.name), target: p.target })
            : M.tn("placements.on", { runner: h("strong", null, p.runner.name) })),
          p.foreign ? h("span", { class: "muted" }, " · ", M.t("placements.foreign")) : null),
        h("dl", { class: "facts" },
          h("dt", null, M.t("placements.runs")), h("dd", null, p.harness + (p.model ? " · " + p.model : "") + " · " + p.mode),
          h("dt", null, M.t("placements.wanted")), h("dd", null, p.desired === "running" ? M.t("placements.state.running") : M.t("placements.state.stopped")),
          // The generation is for the curious: folded into the reported line, muted.
          h("dt", null, M.t("placements.reported")), h("dd", null, stateLine(ctx, p),
            h("span", { class: "muted placement-generation" }, " · ", M.t("placements.generation", { generation: String(p.generation) }),
              p.fresh_session ? [" · ", M.t("placements.fresh_session")] : null,
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
      opts.own ? null : h("p", { class: "muted" }, M.t("placements.hint")), list, status.el);
    // A start from the page's Join an agent form lists its placement at once, not only on its event.
    sections.set(box, reread);
    return box;
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

  // Start on a runner instead of a join line: the section at the end of the one Join an agent
  // form (js/join.js, tsk-hdczmsq2r431; once a form of its own behind a menu). For a human with
  // members:admin, or a member who brings agents of their own (`startOffered`; hooks.member:
  // then only a profile of their own that is not in the project yet, §15.6 "A profile that is
  // not a member yet", tsk-at3gnzqd8svy), over the runners of their own that are attached here
  // with a live credential (§15.4, §15.6) and offer this project's repository (the hub's
  // `repository_not_offered`); none, and why, with the way to allow one, and the join line stays.
  // The form holds the agent and its place in the team; this part holds what the runner
  // advertises (§15.3) and the workspace, and is read when it is turned on. Returns null for
  // whom it is not offered, else:
  // - el: the section; on(): turned on; ready(): on, read, with a tool to start;
  // - follow(agentId, member, handle): the agent the form chose, for what it says about it;
  // - blocked(): why that agent cannot start here now (words), else null;
  // - body(): the runner's part of POST …/placements; said(err): a refusal in words;
  //   refuse(status, err): a refusal into a status line, placement_quota with its link;
  // - reread(): read again while it is on (the panel opened anew, a placement made).
  // hooks.changed(): turned on or off, or read; the form shows and hides its fields.
  // The tools that start only on a model named in the placement: opencode without `--model`
  // runs opencode's own default, an opencode-hosted model, and the clone's conversation would go
  // to opencode's servers (docs/api.md §15.3, docs/runners.md "OpenCode (Grok)"). The form
  // offers such a tool only with the models its runner names, with no "runner's default", and
  // leaves it out where the runner names none (web/context/views.md, the opencode model entry).
  const MODEL_NAMED = new Set(["opencode"]);

  function runnerPart(ctx, hooks) {
    if (!M.placements.startOffered(ctx)) return null;
    const own = !!hooks.member && !ctx.canAdmin;
    const words = M.runnerWords;
    const id = (x) => "placement-new-" + x;
    const field = (key, label, control, hint) => h("div", { class: "field" },
      h("label", { for: id(key) }, label), control, hint ? h("p", { class: "hint", id: id(key) + "-hint" }, hint) : null);
    const select = (key) => h("select", { id: id(key) });
    const input = (key, attrs) => h("input", Object.assign({ id: id(key) }, attrs || {}));

    const offer = h("input", { type: "checkbox", id: id("on"), "aria-describedby": id("on") + "-hint" });
    // What the read brought: the fields, or a line saying why there are none.
    const box = h("div", { class: "join-runner-box" });
    // What the chosen agent means here: not in the project yet, or at its instance limit.
    const why = h("p", { class: "hint join-runner-why", role: "status", hidden: true });
    // An agent that runs already and has room: the next one is another instance (§15.5).
    const another = h("p", { class: "hint join-runner-another", role: "status", hidden: true });
    const el = h("fieldset", { class: "join-runner wide" },
      h("legend", null, M.t("placements.new.legend")),
      h("div", { class: "join-offer" }, offer, " ", h("label", { for: id("on") }, M.t("placements.new.offer"))),
      h("p", { class: "hint", id: id("on") + "-hint" }, M.t("placements.new.hint")),
      why, another, box);
    box.hidden = true;

    let fields = null;          // the controls, once one's runners were read and one offers the repository
    let current = [];           // the project's active placements, read with the runners (§15.5)
    let chosen = { id: "", member: null, handle: "" };
    let round = 0;              // each turning on reads anew; an answer after it was turned off draws nothing

    function build(runners) {
      const runner = select("runner");
      append(runner, runners.map((a) => {
        const c = a.runner.capabilities || {};
        return h("option", { value: a.runner.id }, M.t("placements.new.runner_option", { name: a.runner.name, presence: words.presenceText(a.runner),
          running: String(c.running || 0), max: String(c.max_agents || 0) }));
      }));
      runner.value = runners[0].runner.id;
      const target = select("target");
      const tool = select("tool");
      const mode = select("mode");
      const model = select("model");
      // No tool to start: said with each listed tool's reason (§15.3), not an empty choice alone.
      const noToolWhy = h("ul", { class: "placement-new-no-tool-why" });
      const noTool = h("div", { class: "hint", id: id("tool") + "-none", hidden: true }, h("p", null, M.t("placements.new.no_tool")), noToolWhy);
      // A tool left out because its runner names no model for it (MODEL_NAMED, above).
      const noModel = h("p", { class: "hint placement-new-no-model", id: id("tool") + "-no-model", hidden: true });
      const modelHint = h("p", { class: "hint", id: id("model") + "-hint", hidden: true }, M.t("placements.new.model_named"));
      // A control is described only by the hints shown now: a screen reader reads a hidden
      // element named in aria-describedby too, so a hint that does not apply is not named.
      const describe = (control, hints) => {
        const shown = hints.filter((x) => !x.hidden).map((x) => x.id).join(" ");
        if (shown) control.setAttribute("aria-describedby", shown);
        else control.removeAttribute("aria-describedby");
      };
      const caps = () => (runners.find((a) => a.runner.id === runner.value).runner.capabilities || {});
      const installed = () => (caps().harnesses || []).filter((x) => x.available !== false && (!target.value || (x.targets || []).includes(target.value)));
      const tools = () => installed().filter((x) => !MODEL_NAMED.has(x.id) || (x.models || []).length);
      const harness = () => tools().find((x) => x.id === tool.value);
      const fillModes = () => {
        const x = harness();
        const modes = x ? x.modes || [] : [];
        append(clear(mode), modes.map((m) => h("option", { value: m }, Object.hasOwn(words.MODES, m) ? words.MODES[m] : m)));
        mode.value = x && modes.includes(x.default_mode) ? x.default_mode : modes[0] || "";
        // A tool of MODEL_NAMED starts only on a model chosen here: no "runner's default", and
        // the placeholder keeps the required select empty until one is.
        const named = !!x && MODEL_NAMED.has(x.id);
        append(clear(model), h("option", { value: "" }, named ? M.t("placements.new.model_choose") : M.t("placements.new.model_default")),
          (x ? x.models || [] : []).map((m) => h("option", { value: m }, m)));
        model.required = named;
        modelHint.hidden = !named;
        describe(model, [modelHint]);
      };
      const fillTools = () => {
        const kept = tool.value;
        const list = tools();
        append(clear(tool), list.map((x) => h("option", { value: x.id }, words.toolName(x.id) + (x.version ? " " + x.version : ""))));
        tool.value = list.some((x) => x.id === kept) ? kept : list.length ? list[0].id : "";
        // Nothing to start with: the hub would refuse it (harness_not_offered).
        noTool.hidden = !!list.length;
        const listed = (caps().harnesses || []).filter((x) => !target.value || (x.targets || []).includes(target.value));
        const chosenRunner = runners.find((a) => a.runner.id === runner.value).runner;
        append(clear(noToolWhy), list.length ? [] : !chosenRunner.capabilities ? h("li", null, M.t("runners.caps.unreported"))
          : listed.length ? listed.filter((x) => x.available === false).map((x) => h("li", null, words.unavailableText(chosenRunner, x)))
            : h("li", null, M.t("placements.new.no_tool_listed")));
        const left = installed().filter((x) => !list.includes(x)).map((x) => words.toolName(x.id));
        noModel.hidden = !left.length;
        noModel.textContent = left.length ? M.t("placements.new.no_model", { tools: M.fmt.list(left) }) : "";
        describe(tool, [noTool, noModel]);
        fillModes();
      };
      const fillTargets = () => {
        append(clear(target), h("option", { value: "" }, M.t("placements.new.target_any")),
          (caps().targets || []).filter((x) => x.reachable !== false).map((x) => h("option", { value: x.name }, x.name)));
        fillTools();
      };
      runner.addEventListener("change", fillTargets);
      target.addEventListener("change", fillTools);
      tool.addEventListener("change", fillModes);
      const clone = input("clone", { pattern: "[a-z0-9][a-z0-9\\-]{0,62}", autocomplete: "off", "aria-describedby": id("clone") + "-hint" });
      const branch = input("branch", { autocomplete: "off" });
      // A reason is required while the project plans or is in review (§6.1).
      const needsReason = ["plan", "review"].includes(ctx.project.state);
      const reason = h("textarea", { id: id("reason"), rows: "2", required: needsReason || null });
      // Disabled while the part is off: a disabled fieldset's controls are not validated, so a
      // required reason or a clone's pattern cannot block a join line unseen.
      const set = h("fieldset", { class: "join-runner-fields" },
        field("runner", M.t("placements.new.runner"), runner),
        field("target", M.t("placements.new.target"), target),
        h("div", { class: "field" }, h("label", { for: id("tool") }, M.t("placements.new.tool")), tool, noTool, noModel),
        field("mode", M.t("placements.new.mode"), mode),
        h("div", { class: "field" }, h("label", { for: id("model") }, M.t("placements.new.model")), model, modelHint),
        field("clone", M.t("placements.new.clone"), clone, M.t("placements.new.clone_hint")),
        field("branch", M.t("placements.new.branch"), branch),
        h("div", { class: "field wide" }, h("label", { for: id("reason") },
          needsReason ? M.t("placements.new.reason_required", { state: ctx.project.state }) : M.t("placements.new.reason")), reason));
      fillTargets();
      return { set, runner, target, tool, mode, model, clone, branch, reason };
    }

    // One's runners here and the placements, read each time the part is turned on.
    async function load() {
      const mine = ++round;
      fields = null;
      const say = (node) => { if (mine === round) append(clear(box), node); };
      const repo = ctx.project && ctx.project.repository && ctx.project.repository.url;
      // A project without a repository: the hub refuses every placement, so nothing is read.
      if (!repo) { say(h("p", { class: "hint placement-new-none" }, M.t("placements.new.no_repository"))); return; }
      say(h("p", { class: "muted", role: "status" }, M.t("placements.new.reading")));
      let runners;
      let placements;
      try {
        // With the closed ones too (§15.6 closed=true): a clone a closed placement still holds on a
        // runner is one the hub will not give a start of another member (cloneFor).
        const [attached, listed] = await Promise.all([M.api.getAll(ctx.base + "/runners"), M.api.getAll(ctx.base + "/placements?closed=true")]);
        if (mine !== round) return;
        runners = attached.items.filter((a) => a.runner.owner_id === ctx.me.id && a.runner.credential_state === "active" && !a.runner.removed_at);
        placements = listed.items;
        // The project's list names a runner's capabilities to members:admin only (§15.4); a
        // member reads what their own runners advertise from their own runner views (§15.3).
        if (runners.some((a) => !a.runner.capabilities)) {
          const views = new Map((await M.api.getAll("/runners")).items.map((r) => [r.id, r]));
          if (mine !== round) return;
          runners = runners.map((a) => (views.has(a.runner.id)
            ? Object.assign({}, a, { runner: Object.assign({}, a.runner, { capabilities: views.get(a.runner.id).capabilities }) }) : a));
        }
      } catch (err) {
        say(h("p", { class: "send-status failed" }, M.t("placements.new.runners_failed", { reason: err.message })));
        return;
      }
      if (!runners.length) {
        // The project's Runners tab and attaching a runner are members:admin's (app.js, §15.4):
        // a member is told to ask an admin, with no link to a tab they cannot open.
        say(h("p", { class: "hint placement-new-none" }, ctx.canAdmin
          ? M.tn("placements.new.none", { link: h("a", { href: ctx.link("settings", "runners") }, M.t("placements.new.none_link")) })
          : M.t("placements.new.none_member")));
        return;
      }
      const name = repositoryName(repo);
      runners = runners.filter((a) => ((a.runner.capabilities || {}).repositories || []).some((p) => typeof p === "string" && fnmatch(name, p)));
      if (!runners.length) {
        say(h("p", { class: "hint placement-new-none" }, M.tn("placements.new.no_runner_offers", { repository: h("code", null, name) })));
        return;
      }
      current = placements;
      fields = build(runners);
      fields.runner.addEventListener("change", () => follow(chosen.id, chosen.member, chosen.handle));
      // The clone decides whether a start takes up a credential (carriesCredential): both lines again.
      fields.clone.addEventListener("input", () => follow(chosen.id, chosen.member, chosen.handle));
      say(fields.set);
      follow(chosen.id, chosen.member, chosen.handle);
      hooks.changed();
    }

    offer.addEventListener("change", () => {
      box.hidden = !offer.checked;
      if (offer.checked) load();
      else { round += 1; fields = null; current = []; clear(box); }
      follow(chosen.id, chosen.member, chosen.handle);
      hooks.changed();
    });

    // How many instances a member holds as the hub counts them for a new placement (§15.5): its
    // active instances, plus its active placements that hold no instance yet (no credential
    // before the first pickup), against its `max_instances` (1 when its view names none, §6.18).
    // A placement holds no instance yet when it has no credential, or when the instance its
    // credential made is not among the member's live ones (a revoked credential, waiting to
    // rejoin): the hub counts both (`instances_held`, review A1746 of #2058).
    function instancesOf(member) {
      const liveInstances = (member.instances || []).filter((i) => !i.revoked_at);
      const liveIds = new Set(liveInstances.map((i) => i.id));
      // A members:admin view names each instance's credential (review A1745 of #2058): then a
      // placement's credential among the live ones is what makes it hold a live instance; else
      // its instance id among the live ones.
      const byCredential = liveInstances.some((i) => i.credential_id);
      const liveCredentials = new Set(liveInstances.map((i) => i.credential_id).filter(Boolean));
      // Without credentials named, its instance id among the live ones; with no live instance at
      // all, no placement holds one (review A1815 of #2058).
      const holdsLive = (p) => (byCredential ? liveCredentials.has(p.credential_id) : liveIds.size > 0 && (!p.instance || liveIds.has(p.instance)));
      const mine = current.filter((p) => p.active && p.agent && p.agent.id === member.id);
      const waiting = mine.filter((p) => !p.credential_id || !holdsLive(p)).length;
      const live = liveIds.size;
      // The stored maximum, a hint: a ceiling or the owner's account override can hold the limit
      // in effect lower (§6.31). The member view does not name that one, GET …/limits does
      // (tsk-9zssa5a9fq34 reads it); until then the hub's instance_quota says it (review A1816).
      const max = member.team && Number.isInteger(member.team.max_instances) ? member.team.max_instances : 1;
      const where = [...new Set(mine.map((p) => p.runner && p.runner.name).filter(Boolean))];
      // Its credential is live when a live instance names it, else when the instance it made is.
      const isLive = (p) => (byCredential ? liveCredentials.has(p.credential_id) : !!p.instance && liveIds.has(p.instance));
      const carried = carriesCredential(member, isLive);
      return { count: live + waiting, max, where, carried, adding: carried ? 0 : 1 };
    }
    // Whether a start of `member` on the chosen runner and clone takes up a credential, as the
    // hub does (`carried_credential`, §15.5 "Carried-over credential"): the latest closed
    // placement of that (member, runner, clone) holds a credential that is live and that no
    // active placement runs. Such a start is an instance already and adds none, so it passes at
    // the limit: removing a placement and placing the agent there again (review A1815 of #2058).
    // The hub orders by the stored closing time; the list gives closed_at to the second. Closes
    // within the newest second cannot be told apart here, so when any of them would carry the
    // check is unsure: the start is let through and the hub's answer decides. The form is a hint
    // and never blocks what the hub would take (review A1816 of #2058, the lead's ruling).
    function carriesCredential(member, isLive) {
      if (!fields) return false;
      const clone = fields.clone.value.trim() || cloneFor((member && member.handle) || chosen.handle);
      const closed = current.filter((p) => !p.active && p.agent && p.agent.id === member.id && p.runner
        && p.runner.id === fields.runner.value && p.workspace && p.workspace.clone === clone);
      if (!closed.length) return false;
      const at = (p) => Date.parse(p.closed_at || 0) || 0;
      const newest = Math.max(...closed.map(at));
      const carries = (p) => !!p.credential_id && isLive(p) && !current.some((q) => q.active && q.credential_id === p.credential_id);
      return closed.filter((p) => at(p) === newest).some(carries);
    }
    // §15.6: an agent by id is an active member of the project with room under its instance
    // limit for one more (§15.5: one placement per instance, several per membership), or a
    // profile of the caller's own that is not a member yet, which the placement admits with a
    // first join's fields (the join form offers only the caller's own profiles, GET /agents).
    // A member without members:admin: only that profile of their own; an agent already here, or
    // a new profile, needs members:admin.
    function blocked() {
      if (own) return chosen.id && !chosen.member ? null : M.t("placements.new.own_only");
      // A member that lists no instances (null: the join line's member by the hub's word) gives
      // nothing to count: the hub's instance_quota answers, as the join's quota line leaves it
      // unsaid. The hub's member view of an agent always carries the list (views.py).
      if (!chosen.id || !chosen.member || chosen.member.instances === null) return null;
      const n = instancesOf(chosen.member);
      if (n.count + n.adding > n.max) return M.t("placements.new.instance_full", { name: chosen.member.display_name || chosen.member.handle, active: String(n.count), max: String(n.max) });
      return null;
    }
    // An agent that runs already, with room: what the start adds and where the others run. A
    // start that takes up a credential adds no instance, so nothing is said.
    function anotherText() {
      // Not before the placements are read: where the others run is not known until then.
      if (!fields || !chosen.member || chosen.member.instances === null || blocked()) return null;
      const n = instancesOf(chosen.member);
      if (!n.count || n.carried) return null;
      const where = n.where.length ? M.t("placements.new.instance_where", { runners: M.fmt.list(n.where) }) : M.t("placements.new.instance_where_none");
      return M.t("placements.new.instance_room", { name: chosen.member.display_name || chosen.member.handle, active: String(n.count), max: String(n.max), where });
    }
    // The clone a start without one gets, as the hub picks it (§15.5 `workspace`): the handle,
    // else the first `<handle>-N` that on the chosen runner no active placement names, nor a
    // closed one of another member whose clone the runner has not reported removed (the member's
    // own closed clone is taken up again; review A1746 of #2058).
    function cloneFor(handle) {
      if (!fields || !handle) return handle;
      const holds = (p) => p.active || ((!p.agent || p.agent.id !== chosen.id)
        && !(p.workspace_outcome && p.workspace_outcome.state === "removed"));
      const taken = new Set(current.filter((p) => p.runner && p.runner.id === fields.runner.value && holds(p))
        .map((p) => p.workspace && p.workspace.clone).filter(Boolean));
      if (!taken.has(handle)) return handle;
      let n = 2;
      while (taken.has(handle + "-" + n)) n += 1;
      return handle + "-" + n;
    }
    function follow(agentId, member, handle) {
      chosen = { id: agentId || "", member: member || null, handle: handle || "" };
      const text = offer.checked ? blocked() : null;
      why.hidden = !text;
      why.textContent = text || "";
      const more = offer.checked ? anotherText() : null;
      another.hidden = !more;
      another.textContent = more || "";
      if (fields) fields.set.disabled = !offer.checked;
      // The clone the hub would give: for an agent here or a new profile's handle alike.
      const named = (member && member.handle) || chosen.handle;
      if (fields) fields.clone.setAttribute("placeholder", named ? cloneFor(named) : M.t("placements.new.clone_placeholder"));
    }

    function body() {
      const f = fields;
      const b = { runner: f.runner.value, target: f.target.value || null, harness: f.tool.value };
      if (f.mode.value) b.mode = f.mode.value;
      b.model = f.model.value || null;
      const workspace = {};
      if (f.clone.value.trim()) workspace.clone = f.clone.value.trim();
      if (f.branch.value.trim()) workspace.branch = f.branch.value.trim();
      if (Object.keys(workspace).length) b.workspace = workspace;
      if (f.reason.value.trim()) b.reason = f.reason.value.trim();
      return b;
    }
    // A refusal as the hub sends it; the fields it names, each with its code.
    const said = (err) => {
      const named = err.code === "invalid" && err.details && err.details.fields;
      const list = named ? Object.entries(named).map(([k, v]) => M.t("placements.new.field", { field: k, why: v })).join("; ") : "";
      const text = err.code ? M.t("placements.refusal", { reason: err.message || M.t("placements.an_error"), code: err.code }) : err.message || M.t("placements.an_error");
      return { message: list ? text + " — " + list : text };
    };
    // A refusal into the form's status line: the project's limit of placements reached by name,
    // with where a human admin raises it (§6.1 max_placements, tsk-6s5n7egy4e5r); else said(err).
    const refuse = (status, err) => {
      // The agent at its instance limit, by the hub (a start that raced another, §15.5): the
      // limit in effect and who raises it, as the form says before sending (blocked()).
      if (err.code === "instance_quota") {
        const n = chosen.member ? instancesOf(chosen.member) : { max: 1 };
        const max = err.details && Number.isInteger(err.details.max) ? err.details.max : n.max;
        status.fail(M.t("placements.new.failed"), { message: M.t("placements.new.instance_quota", { max: String(max) }) });
        return;
      }
      if (err.code !== "placement_quota") { status.fail(M.t("placements.new.failed"), said(err)); return; }
      const max = err.details && Number.isInteger(err.details.max) ? err.details.max : (ctx.project.policy || {}).max_placements;
      status.fail(M.t("placements.new.failed"), { message: M.t("placements.new.quota", { max: max === undefined ? 8 : max }) });
      // Settings, Members and agents is an admin's tab (app.js): a member asks an admin instead.
      append(status.el, " ", ctx.canAdmin
        ? M.tn("placements.new.quota_raise",
          { link: h("a", { href: ctx.link("settings", "members"), class: "placement-quota-link" }, M.t("placements.new.quota_link")) })
        : M.t("placements.new.quota_ask"));
    };
    return {
      el,
      on: () => offer.checked,
      ready: () => offer.checked && !!fields && !!fields.tool.value,
      // A tool that needs a model named (MODEL_NAMED) without one chosen: words, else null.
      unnamed: () => (fields && fields.model.required && !fields.model.value ? M.t("placements.new.model_missing", { tool: words.toolName(fields.tool.value) }) : null),
      first: () => (fields ? fields.runner : offer),
      model: () => (fields ? fields.model : offer),
      follow, blocked, body, said, refuse,
      reread: () => { if (offer.checked) load(); },
    };
  }

  // The sections drawn, each with its way to read the list again (`reread(box)`).
  const sections = new WeakMap();
  const reread = (box) => (sections.has(box) ? sections.get(box)() : Promise.resolve());
  // A human with members:admin, or a member who brings agents of their own here (§3.1, §15.6;
  // M.bringing in js/page-head.js: trust member, the policy's member_agents not off).
  const startOffered = (ctx) => ctx.me.kind === "human" && (!!ctx.canAdmin || (!!M.bringing && M.bringing(ctx).memberAdds));
  M.placements = { section, runnerPart, startOffered, reread, fnmatch };
})(window.Maity);
