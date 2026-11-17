// Where the project's agents run (docs/api.md §15.5–§15.7), inside the
// Agents view: one row per placement — agent, runner, harness and model,
// what is wanted (`desired`), what the runner last reported, the
// generation — with Stop for the runner's owner and the agent profile's
// owner, Start and Restart for the runner's side only (§15.6: the runner's
// owner, with members:admin or as the profile's owner), and Remove for a
// placement made before only the runner's owner could (`foreign`). Stop
// asks nothing, it is the safe direction; a restart is confirmed with one
// more click. A placement waiting for consent links to
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
    const owns = (p) => {
      const m = p.agent && p.agent.id && ctx.memberById ? ctx.memberById[p.agent.id] : null;
      return !!m && m.owner_id === ctx.me.id;
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
      // Ended by the runner's owner or the profile's owner, who places it again on a
      // runner of their own: a foreign one does not move otherwise (§15.5, §15.14).
      const remove = h("button", { type: "button", class: "danger", "aria-label": M.t("placements.remove.label", { name }),
        onclick: () => {
          if (!window.confirm(M.t("placements.remove.ask", { name }))) return;
          act(p, M.t("placements.removing"), M.t("placements.not_removed"), () => M.api.del(path(p)), row);
        } }, M.t("placements.remove"));
      const starts = mayStart(p);
      append(row, p.desired === "running" ? stop : starts ? start : null,
        starts ? [" ", restartWith(false), revoked(p) ? [" ", restartWith(true)] : null] : null,
        p.foreign ? [" ", remove] : null);
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
            : M.tn("placements.on", { runner: h("strong", null, p.runner.name) })),
          p.foreign ? h("span", { class: "muted" }, " · ", M.t("placements.foreign")) : null),
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
      opts.own ? null : h("p", { class: "muted" }, M.t("placements.hint")), list, status.el);
    // A start from the page's Join an agent menu lists its placement at once, not only on its event.
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
  // members:admin only (`startOffered`), over the runners of their own that are attached here
  // with a live credential (§15.4, §15.6) and offer this project's repository (the hub's
  // `repository_not_offered`); none, and why, with the way to allow one, and the join line stays.
  // The form holds the agent and its place in the team; this part holds what the runner
  // advertises (§15.3) and the workspace, and is read when it is turned on. Returns null for
  // whom it is not offered, else:
  // - el: the section; on(): turned on; ready(): on, read, with a tool to start;
  // - follow(agentId, member, handle): the agent the form chose, for what it says about it;
  // - blocked(): why that agent cannot start here now (words), else null;
  // - body(): the runner's part of POST …/placements; said(err): a refusal in words;
  // - reread(): read again while it is on (the panel opened anew, a placement made).
  // hooks.changed(): turned on or off, or read; the form shows and hides its fields.
  function runnerPart(ctx, hooks) {
    if (!M.placements.startOffered(ctx)) return null;
    const words = M.runnerWords;
    const id = (x) => "placement-new-" + x;
    const field = (key, label, control, hint) => h("div", { class: "field" },
      h("label", { for: id(key) }, label), control, hint ? h("p", { class: "hint", id: id(key) + "-hint" }, hint) : null);
    const select = (key) => h("select", { id: id(key) });
    const input = (key, attrs) => h("input", Object.assign({ id: id(key) }, attrs || {}));

    const offer = h("input", { type: "checkbox", id: id("on"), "aria-describedby": id("on") + "-hint" });
    // What the read brought: the fields, or a line saying why there are none.
    const box = h("div", { class: "join-runner-box" });
    // What the chosen agent means here: not in the project yet, or placed already.
    const why = h("p", { class: "hint join-runner-why", role: "status", hidden: true });
    const el = h("fieldset", { class: "join-runner wide" },
      h("legend", null, M.t("placements.new.legend")),
      h("div", { class: "join-offer" }, offer, " ", h("label", { for: id("on") }, M.t("placements.new.offer"))),
      h("p", { class: "hint", id: id("on") + "-hint" }, M.t("placements.new.hint")),
      why, box);
    box.hidden = true;

    let fields = null;          // the controls, once one's runners were read and one offers the repository
    let placed = new Set();     // the agents with an active placement here (§15.5)
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
      tool.setAttribute("aria-describedby", id("tool") + "-none");
      const mode = select("mode");
      const model = select("model");
      const noTool = h("p", { class: "hint", id: id("tool") + "-none", hidden: true }, M.t("placements.new.no_tool"));
      const caps = () => (runners.find((a) => a.runner.id === runner.value).runner.capabilities || {});
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
        // Nothing to start with: the hub would refuse it (harness_not_offered).
        noTool.hidden = !!list.length;
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
        h("div", { class: "field" }, h("label", { for: id("tool") }, M.t("placements.new.tool")), tool, noTool),
        field("mode", M.t("placements.new.mode"), mode),
        field("model", M.t("placements.new.model"), model),
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
      try {
        const [attached, current] = await Promise.all([M.api.getAll(ctx.base + "/runners"), M.api.getAll(ctx.base + "/placements")]);
        if (mine !== round) return;
        runners = attached.items.filter((a) => a.runner.owner_id === ctx.me.id && a.runner.credential_state === "active" && !a.runner.removed_at);
        placed = new Set(current.items.filter((p) => p.active && p.agent.id).map((p) => p.agent.id));
      } catch (err) {
        say(h("p", { class: "send-status failed" }, M.t("placements.new.runners_failed", { reason: err.message })));
        return;
      }
      if (!runners.length) {
        say(h("p", { class: "hint placement-new-none" }, M.tn("placements.new.none",
          { link: h("a", { href: ctx.link("runners") }, M.t("placements.new.none_link")) })));
        return;
      }
      const name = repositoryName(repo);
      runners = runners.filter((a) => ((a.runner.capabilities || {}).repositories || []).some((p) => typeof p === "string" && fnmatch(name, p)));
      if (!runners.length) {
        say(h("p", { class: "hint placement-new-none" }, M.tn("placements.new.no_runner_offers", { repository: h("code", null, name) })));
        return;
      }
      fields = build(runners);
      say(fields.set);
      follow(chosen.id, chosen.member, chosen.handle);
      hooks.changed();
    }

    offer.addEventListener("change", () => {
      box.hidden = !offer.checked;
      if (offer.checked) load();
      else { round += 1; fields = null; clear(box); }
      follow(chosen.id, chosen.member, chosen.handle);
      hooks.changed();
    });

    // §15.6: an agent by id is an active member of the project; one placed here already has its
    // placement (§15.5, one per membership).
    function blocked() {
      if (!chosen.id) return null;
      if (!chosen.member) return M.t("placements.new.not_member");
      if (placed.has(chosen.id)) return M.t("placements.new.placed");
      return null;
    }
    function follow(agentId, member, handle) {
      chosen = { id: agentId || "", member: member || null, handle: handle || "" };
      const text = offer.checked ? blocked() : null;
      why.hidden = !text;
      why.textContent = text || "";
      if (fields) fields.set.disabled = !offer.checked;
      if (fields) fields.clone.setAttribute("placeholder", member ? member.handle : chosen.handle || M.t("placements.new.clone_placeholder"));
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
    return {
      el,
      on: () => offer.checked,
      ready: () => offer.checked && !!fields && !!fields.tool.value,
      first: () => (fields ? fields.runner : offer),
      follow, blocked, body, said,
      reread: () => { if (offer.checked) load(); },
    };
  }

  // The sections drawn, each with its way to read the list again (`reread(box)`).
  const sections = new WeakMap();
  const reread = (box) => (sections.has(box) ? sections.get(box)() : Promise.resolve());
  const startOffered = (ctx) => !!ctx.canAdmin && ctx.me.kind === "human";
  M.placements = { section, runnerPart, startOffered, reread, fnmatch };
})(window.Maity);
