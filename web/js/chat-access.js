// Who may chat with one's agents (docs/api.md §9.6, "The lists"): the allow and deny entries of
// GET /me/chat-access, each removed on its row, an allow edited in place, and a form for each kind.
// The /agents page's tab Chat access (/agents/chat-access, js/agents-page.js).
//
// The hub answers ids only where an entry names an agent; a person is named by the handle the
// entry carries. Whom a new entry names is chosen from the members of the reader's own projects
// (GET /people/{handle} answers no id), and a project from the reader's projects.
"use strict";
window.Maity = window.Maity || {};
(function (M) {
  const { h, append, clear, formatTime } = M.dom;
  const PATH = "/me/chat-access";
  const TEXT_MAX = 1000;
  const DURATIONS = [
    ["hour", () => M.t("chat_access.duration.hour")],
    ["day", () => M.t("chat_access.duration.day")],
    ["week", () => M.t("chat_access.duration.week")],
    ["", () => M.t("chat_access.duration.always")],
  ];
  let seq = 0;
  const uid = (name) => "chat-access-" + name + "-" + (++seq);

  // Whom the reader may name: the people and the other owners' agents in the member lists of the
  // reader's projects, read once per view (M.membersOnce); a list that fails is left out.
  async function known(ctx) {
    const humans = new Map(), agents = new Map();
    const lists = await Promise.all((ctx.projects || []).map((p) => M.membersOnce(ctx, p.full_name).then((r) => r.items, () => [])));
    lists.flat().forEach((m) => {
      if (m.removed_at) return;
      if (m.kind === "human" && m.id !== ctx.me.id) humans.set(m.id, m);
      if (m.kind === "agent" && m.owner_id !== ctx.me.id) agents.set(m.id, m);
    });
    const byHandle = (a, b) => String(a.handle).localeCompare(String(b.handle));
    return { humans: [...humans.values()].sort(byHandle), agents: [...agents.values()].sort(byHandle) };
  }

  // One's own agents ticked, or all of them, as an entry's `agents` takes them.
  function agentsField(profiles, chosen, legend) {
    const id = uid("all");
    const all = h("input", { type: "checkbox", id });
    all.checked = chosen === "all";
    const ticks = profiles.map((a) => {
      const box = h("input", { type: "checkbox", id: uid("agent") });
      box.checked = chosen !== "all" && (chosen || []).includes(a.id);
      return { a, box };
    });
    const show = () => ticks.forEach((t) => { t.box.disabled = all.checked; });
    all.addEventListener("change", show);
    show();
    return {
      el: h("fieldset", { class: "chat-access-agents field-stack" }, h("legend", null, legend),
        h("label", { class: "check", for: id }, all, " " + M.t("chat_access.all_agents")),
        ticks.map((t) => h("label", { class: "check", for: t.box.id }, t.box, " " + t.a.display_name,
          h("span", { class: "muted" }, " @" + t.a.handle)))),
      value: () => (all.checked ? "all" : ticks.filter((t) => t.box.checked).map((t) => t.a.id)),
    };
  }

  function select(id, options, value) {
    const el = h("select", { id }, options.map(([v, label]) => h("option", { value: v }, label)));
    // The first option where none is given, as a browser shows it (and the smoke test's DOM does not).
    el.value = value !== undefined ? value : options.length ? options[0][0] : "";
    return el;
  }

  function textField(label, value) {
    const id = uid("text");
    const el = h("textarea", { id, rows: "2", maxlength: String(TEXT_MAX) });
    el.value = value || "";
    return { el, nodes: [h("label", { for: id }, label), el] };
  }

  // A rule as the hub keeps it: the text, or null for none.
  const ruleOf = (field) => field.el.value.trim() || null;

  function part(ctx, profiles) {
    const box = h("section", { class: "chat-access-page", "aria-labelledby": "chat-access-heading" },
      h("h2", { id: "chat-access-heading", tabindex: "-1" }, M.t("chat_access.title")),
      h("p", { class: "hint" }, M.t("chat_access.hint")));
    const status = M.statusLine();
    const body = h("div");
    append(box, status.el, body);
    let people = { humans: [], agents: [] };
    const ownName = (id) => { const a = profiles.find((p) => p.id === id); return a ? "@" + a.handle : id; };
    const agentName = (id) => { const a = people.agents.find((x) => x.id === id); return a ? "@" + a.handle : id; };
    const agentsText = (agents) => (agents === "all" ? M.t("chat_access.all_agents") : agents.map(ownName).join(", "));
    const projectText = (p) => p.owner + "/" + p.slug;

    async function load(words) {
      status.busy(M.t("chat_access.reading"));
      try {
        const [lists, found] = await Promise.all([M.api.get(PATH), known(ctx)]);
        people = found;
        status.done();
        draw(lists, words);
      } catch (err) {
        status.fail(M.t("chat_access.read_failed"), err);
      }
    }

    // What an allow entry admits: a side (the agents of it the entry names, its human or not) or a project.
    function whom(e) {
      if (e.project) return M.t("chat_access.project", { project: projectText(e.project) });
      const theirs = e.their_agents === "all" ? M.t("chat_access.their_all")
        : e.their_agents === "none" ? M.t("chat_access.their_none")
          : M.t("chat_access.their_named", { agents: e.their_agents.map(agentName).join(", ") });
      return [M.t("chat_access.side", { handle: e.handle || e.owner_id }), " · ", theirs, " · ",
        e.their_human ? M.t("chat_access.human_yes", { handle: e.handle || e.owner_id }) : M.t("chat_access.human_no", { handle: e.handle || e.owner_id })];
    }

    function when(e) {
      if (!e.duration) return M.t("chat_access.for_good");
      if (e.until && Date.parse(e.until) <= Date.now()) return M.t("chat_access.ended", { at: formatTime(e.until) });
      return M.t("chat_access.until", { at: formatTime(e.until) });
    }

    function denied(e) {
      if (e.project) return M.t("chat_access.project", { project: projectText(e.project) });
      if (e.agent_id) return M.t("chat_access.deny.agent", { agent: agentName(e.agent_id) });
      if (e.human_id) return M.t("chat_access.deny.person", { handle: e.handle || e.human_id });
      return M.t("chat_access.deny.side", { handle: e.handle || e.owner_id });
    }

    function remove(kind, e) {
      return h("button", { type: "button", class: "danger", onclick: async (ev) => {
        if (!window.confirm(kind === "allow" ? M.t("chat_access.remove_allow_confirm") : M.t("chat_access.remove_deny_confirm"))) return;
        ev.target.disabled = true;
        status.busy(M.t("chat_access.removing"));
        try {
          await M.api.del(PATH + "/" + kind + "/" + encodeURIComponent(e.id));
          status.done();
          load(M.t("chat_access.removed"));
        } catch (err) {
          ev.target.disabled = false;
          status.fail(M.t("chat_access.remove_failed"), err);
        }
      } }, M.t("chat_access.remove"));
    }

    // An allow entry edited in place: only what changed is sent; a duration chosen starts again from now.
    function editForm(e, close) {
      const agents = agentsField(profiles, e.agents, M.t("chat_access.agents"));
      const duration = select(uid("duration"), [["keep", M.t("chat_access.duration.keep")]].concat(DURATIONS.map(([v, l]) => [v, l()])), "keep");
      const side = !e.project;
      const theirId = uid("their");
      const theirOptions = [["all", M.t("chat_access.their_all")], ["none", M.t("chat_access.their_none")]];
      if (side && Array.isArray(e.their_agents)) theirOptions.push(["keep", M.t("chat_access.their_named", { agents: e.their_agents.map(agentName).join(", ") })]);
      const their = side ? select(theirId, theirOptions, Array.isArray(e.their_agents) ? "keep" : e.their_agents) : null;
      const humanId = uid("human");
      const human = side ? h("input", { type: "checkbox", id: humanId }) : null;
      if (human) human.checked = !!e.their_human;
      const allowed = textField(M.t("chat_access.allowed"), e.allowed);
      const deniedText = textField(M.t("chat_access.denied"), e.denied);
      const durationId = duration.id;
      const save = h("button", { type: "submit" }, M.t("chat_access.save"));
      const form = h("form", { class: "inline-form chat-access-edit field-stack" },
        agents.el,
        h("label", { for: durationId }, M.t("chat_access.duration_label")), duration,
        side ? [h("label", { for: theirId }, M.t("chat_access.their_agents", { handle: e.handle || e.owner_id })), their,
          h("label", { class: "check", for: humanId }, human, " " + M.t("chat_access.their_human", { handle: e.handle || e.owner_id }))] : null,
        allowed.nodes, deniedText.nodes,
        h("div", { class: "actions" }, save, h("button", { type: "button", onclick: close }, M.t("chat_access.cancel"))));
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const patch = {};
        const a = agents.value();
        if (JSON.stringify(a) !== JSON.stringify(e.agents)) patch.agents = a;
        if (duration.value !== "keep") patch.duration = duration.value || null;
        if (their && their.value !== "keep" && their.value !== e.their_agents) patch.their_agents = their.value;
        if (human && human.checked !== !!e.their_human) patch.their_human = human.checked;
        if (ruleOf(allowed) !== (e.allowed || null)) patch.allowed = ruleOf(allowed);
        if (ruleOf(deniedText) !== (e.denied || null)) patch.denied = ruleOf(deniedText);
        if (!Object.keys(patch).length) { close(); return; }
        save.disabled = true;
        status.busy(M.t("chat_access.saving"));
        try {
          await M.api.patch(PATH + "/allow/" + encodeURIComponent(e.id), patch);
          status.done();
          load(M.t("chat_access.saved"));
        } catch (err) {
          save.disabled = false;
          status.fail(M.t("chat_access.save_failed"), err);
        }
      });
      return form;
    }

    function allowRow(e) {
      const row = h("li", { class: "chat-access-entry" });
      const slot = h("div");
      const edit = h("button", { type: "button", "aria-expanded": "false", onclick: () => {
        if (slot.firstChild) { clear(slot); edit.setAttribute("aria-expanded", "false"); return; }
        append(slot, editForm(e, () => { clear(slot); edit.setAttribute("aria-expanded", "false"); }));
        edit.setAttribute("aria-expanded", "true");
      } }, M.t("chat_access.edit"));
      append(row,
        h("p", { class: "chat-access-whom" }, h("strong", null, whom(e))),
        h("p", { class: "muted" }, M.t("chat_access.for_agents", { agents: agentsText(e.agents) }), " · ", when(e)),
        e.allowed ? h("p", null, M.t("chat_access.allowed_said"), " ", h("q", null, e.allowed)) : null,
        e.denied ? h("p", null, M.t("chat_access.denied_said"), " ", h("q", null, e.denied)) : null,
        h("div", { class: "actions" }, edit, remove("allow", e)), slot);
      return row;
    }

    function denyRow(e) {
      const row = h("li", { class: "chat-access-entry" });
      append(row,
        h("p", { class: "chat-access-whom" }, h("strong", null, denied(e))),
        h("p", { class: "muted" }, M.t("chat_access.for_agents", { agents: agentsText(e.agents) }), " · ", M.t("chat_access.since", { at: formatTime(e.since) })),
        h("div", { class: "actions" }, remove("deny", e)));
      return row;
    }

    // Whom a new entry names: a side, one person, one agent or a project (`kinds`, in that order of choice).
    function subjectField(kinds) {
      const kindId = uid("subject");
      const labels = { owner_id: M.t("chat_access.subject.side"), human_id: M.t("chat_access.subject.person"),
        agent_id: M.t("chat_access.subject.agent"), project: M.t("chat_access.subject.project") };
      const kind = select(kindId, kinds.map((k) => [k, labels[k]]));
      const personId = uid("person"), agentId = uid("other-agent"), projectId = uid("project");
      const person = select(personId, [["", M.t("chat_access.choose")]].concat(people.humans.map((m) => [m.id, "@" + m.handle + " (" + m.display_name + ")"])));
      const agent = select(agentId, [["", M.t("chat_access.choose")]].concat(people.agents.map((m) => [m.id, "@" + m.handle + " (" + m.display_name + ")"])));
      const project = select(projectId, [["", M.t("chat_access.choose")]].concat((ctx.projects || []).map((p) => [p.full_name, p.full_name])));
      const rows = {
        person: h("div", { class: "field-stack" }, h("label", { for: personId }, M.t("chat_access.person")), person,
          people.humans.length ? null : h("p", { class: "muted" }, M.t("chat_access.no_people"))),
        agent: h("div", { class: "field-stack" }, h("label", { for: agentId }, M.t("chat_access.other_agent")), agent,
          people.agents.length ? null : h("p", { class: "muted" }, M.t("chat_access.no_agents"))),
        project: h("div", { class: "field-stack" }, h("label", { for: projectId }, M.t("chat_access.project_label")), project),
      };
      const listeners = [];
      const show = () => {
        rows.person.hidden = !["owner_id", "human_id"].includes(kind.value);
        rows.agent.hidden = kind.value !== "agent_id";
        rows.project.hidden = kind.value !== "project";
        listeners.forEach((f) => f(kind.value));
      };
      kind.addEventListener("change", show);
      return {
        nodes: [h("label", { for: kindId }, M.t("chat_access.subject_label")), kind, rows.person, rows.agent, rows.project],
        kind: () => kind.value,
        onChange: (f) => { listeners.push(f); },
        show,
        // The subject as the hub takes it, or null with the field to point at when nothing is chosen.
        value: () => {
          const k = kind.value;
          if (k === "project") {
            if (!project.value) return { missing: project };
            const [owner, slug] = project.value.split("/");
            return { project: { owner, slug } };
          }
          const el = k === "agent_id" ? agent : person;
          return el.value ? { [k]: el.value } : { missing: el };
        },
      };
    }

    function addForm(kind) {
      const allow = kind === "allow";
      const agents = agentsField(profiles, "all", M.t("chat_access.agents"));
      const subject = subjectField(allow ? ["owner_id", "project"] : ["owner_id", "human_id", "agent_id", "project"]);
      const theirId = uid("their"), humanId = uid("human"), durationId = uid("duration");
      const their = select(theirId, [["all", M.t("chat_access.their_all")], ["none", M.t("chat_access.their_none")]], "all");
      const human = h("input", { type: "checkbox", id: humanId });
      const sideOnly = h("div", { class: "field-stack" },
        h("label", { for: theirId }, M.t("chat_access.their_agents_new")), their,
        h("label", { class: "check", for: humanId }, human, " " + M.t("chat_access.their_human_new")));
      const duration = select(durationId, DURATIONS.map(([v, l]) => [v, l()]), "");
      const allowed = textField(M.t("chat_access.allowed"));
      const deniedText = textField(M.t("chat_access.denied"));
      const error = h("p", { class: "field-error", role: "alert" });
      const save = h("button", { type: "submit" }, allow ? M.t("chat_access.add_allow") : M.t("chat_access.add_deny"));
      subject.onChange((k) => { sideOnly.hidden = k !== "owner_id"; });
      const form = h("form", { class: "inline-form chat-access-add field-stack", novalidate: true },
        h("h3", null, allow ? M.t("chat_access.new_allow") : M.t("chat_access.new_deny")),
        agents.el, subject.nodes,
        allow ? [sideOnly, h("label", { for: durationId }, M.t("chat_access.duration_label")), duration, allowed.nodes, deniedText.nodes] : null,
        error, h("div", { class: "actions" }, save));
      subject.show();
      form.addEventListener("submit", async (ev) => {
        ev.preventDefault();
        error.textContent = "";
        const a = agents.value();
        if (a !== "all" && !a.length) { error.textContent = M.t("chat_access.choose_agents"); return; }
        const s = subject.value();
        if (s.missing) { error.textContent = M.t("chat_access.choose_subject"); s.missing.focus(); return; }
        const sent = Object.assign({ agents: a }, s);
        if (allow) {
          if (subject.kind() === "owner_id") Object.assign(sent, { their_agents: their.value, their_human: human.checked });
          if (duration.value) sent.duration = duration.value;
          if (ruleOf(allowed)) sent.allowed = ruleOf(allowed);
          if (ruleOf(deniedText)) sent.denied = ruleOf(deniedText);
        }
        save.disabled = true;
        status.busy(M.t("chat_access.saving"));
        try {
          await M.api.post(PATH + "/" + kind, sent);
          status.done();
          load(allow ? M.t("chat_access.allow_added") : M.t("chat_access.deny_added"));
        } catch (err) {
          save.disabled = false;
          status.fail(M.t("chat_access.save_failed"), err);
        }
      });
      return form;
    }

    function draw(lists, words) {
      clear(body);
      append(body,
        words ? h("p", { class: "ok", role: "status" }, words) : null,
        h("h3", null, M.t("chat_access.allow_title")),
        lists.allow.length ? h("ul", { class: "chat-access-list allow" }, lists.allow.map(allowRow))
          : h("p", { class: "muted" }, M.t("chat_access.no_allow")),
        h("h3", null, M.t("chat_access.deny_title")),
        lists.deny.length ? h("ul", { class: "chat-access-list deny" }, lists.deny.map(denyRow))
          : h("p", { class: "muted" }, M.t("chat_access.no_deny")),
        profiles.length ? [addForm("allow"), addForm("deny")] : h("p", { class: "muted" }, M.t("agents.none")));
    }

    load();
    return box;
  }

  M.chatAccess = { part };
})(window.Maity);
