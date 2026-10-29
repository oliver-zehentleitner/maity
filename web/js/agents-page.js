// Your agents (/agents, docs/api.md §6.3, §16.11): every agent profile of the
// human, across projects, from the gear menu beside Runners. Each profile
// with its picture, its memberships (project, trust and role, the instances
// against the team's limit), Add to a project, its name, git identity and
// handle, and its deletion; a new profile at the top. Adding to a project is
// the join panel on that project's Members (js/join.js), opened with the
// profile chosen: one component, in the project and from here.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const HANDLE = M.dom.NAME_RULES.handle;

  // The hub's refusals of a profile's fields (§6.3, §6.24), in words.
  const FIELD_WORDS = {
    taken: "you have a profile with this handle already, or had one by that name",
    reserved: "a word the dashboard uses itself",
    string_pattern_mismatch: HANDLE.text,
    string_too_short: "required",
    invalid: "a name and an address like name@example.org, or both empty",
  };
  function said(err) {
    const fields = err.code === "invalid" && err.details && err.details.fields;
    if (fields) return { message: Object.entries(fields).map(([k, v]) => k.replace("_", " ") + ": " + (FIELD_WORDS[v] || v)).join("; ") };
    if (err.code === "alias_limit") return { message: "the profile has kept as many earlier handles as it may" };
    if (err.code === "rate_limited") return { message: "too many changes just now; try again later" };
    return err;
  }

  // A project one may bring an agent into: one's trust there is owner or
  // admin, or member where the project lets members bring their own (§3.1);
  // the join panel there says the rest.
  const mayBring = (p) => ["owner", "admin", "member"].includes(p.trust);

  function newProfile(done) {
    const status = M.statusLine();
    const handle = h("input", { id: "agent-new-handle", required: true, autocomplete: "off", spellcheck: "false", pattern: HANDLE.pattern, maxlength: "31" });
    const name = h("input", { id: "agent-new-name", required: true, maxlength: "100", autocomplete: "off" });
    const go = h("button", { type: "submit" }, "Create the profile");
    return h("form", {
      class: "agent-new project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        go.disabled = true;
        status.busy("Creating…");
        try {
          const made = await M.api.post("/agents", { handle: handle.value.trim().replace(/^@/, ""), display_name: name.value.trim() });
          done(made, "The profile @" + made.handle + " was created. Add it to a project to give it a join line.");
        } catch (err) {
          status.fail("Not created: ", said(err));
          go.disabled = false;
        }
      },
    },
    h("h3", null, "New agent profile"),
    h("label", { for: "agent-new-handle" }, "Handle"), handle, h("p", { class: "hint" }, HANDLE.text),
    h("label", { for: "agent-new-name" }, "Display name"), name,
    go, status.el);
  }

  // A membership's line: the project, trust and role, the instances against
  // the team's limit as that project's member view has them.
  function membershipLine(ctx, a, m, view) {
    const active = view ? (view.instances || []).filter((i) => !i.revoked_at).length : null;
    const max = view && view.team ? view.team.max_instances : null;
    return h("li", { class: "agent-membership" },
      h("a", { href: "/" + M.api.projectPath(m.project) + "/members/" + encodeURIComponent(a.id) }, m.project),
      h("span", { class: "muted" }, " · " + M.trust.words(m)),
      active === null ? null : h("span", { class: "muted" }, " · " + active + (max ? " of " + max : "") + (active === 1 ? " instance" : " instances") + " active"),
      " ", h("a", { class: "small", href: "/" + M.api.projectPath(m.project) + "/members/" + encodeURIComponent(a.id) + "/rulebook" }, "Team rulebook"));
  }

  function addToProject(ctx, a) {
    const projects = (ctx.projects || []).filter(mayBring);
    if (!projects.length) return h("p", { class: "muted" }, "You are in no project you may bring an agent into.");
    const id = "agent-add-" + a.id;
    const pick = h("select", { id }, projects.map((p) => h("option", { value: p.full_name }, p.name + " (" + p.full_name + ")")));
    pick.value = projects[0].full_name;
    const go = h("button", { type: "submit" }, "Add to the project");
    return h("form", {
      class: "agent-add inline-form",
      onsubmit: (e) => {
        e.preventDefault();
        // The project's own join panel, this profile chosen: there its rules apply.
        M.route.go("/" + M.api.projectPath(pick.value) + "/members/join?agent=" + encodeURIComponent(a.id));
      },
    }, h("label", { for: id }, "Add to a project"), pick, go,
    h("p", { class: "hint" }, "Opens the project's Members with the join panel, this profile chosen. "
      + "In a project it is already in, the line starts another instance or replaces one."));
  }

  function editForm(a, done) {
    const status = M.statusLine();
    const key = (k) => "agent-" + k + "-" + a.id;
    const name = h("input", { id: key("name"), required: true, maxlength: "100" });
    name.value = a.display_name;
    const handle = h("input", { id: key("handle"), required: true, autocomplete: "off", spellcheck: "false", pattern: HANDLE.pattern, maxlength: "31" });
    handle.value = a.handle;
    const gitName = h("input", { id: key("git-name"), autocomplete: "off" });
    gitName.value = (a.git_identity && a.git_identity.name) || "";
    const gitMail = h("input", { id: key("git-email"), type: "email", autocomplete: "off" });
    gitMail.value = (a.git_identity && a.git_identity.email) || "";
    const go = h("button", { type: "submit" }, "Save");
    return h("form", {
      class: "agent-edit project-form",
      onsubmit: async (e) => {
        e.preventDefault();
        const body = {};
        if (name.value.trim() !== a.display_name) body.display_name = name.value.trim();
        const wanted = handle.value.trim().replace(/^@/, "");
        if (wanted !== a.handle) body.handle = wanted;
        const git = gitName.value.trim() || gitMail.value.trim() ? { name: gitName.value.trim(), email: gitMail.value.trim() } : null;
        if (JSON.stringify(git) !== JSON.stringify(a.git_identity || null)) body.git_identity = git;
        if (!Object.keys(body).length) { status.busy("Nothing changed."); return; }
        go.disabled = true;
        status.busy("Saving…");
        try {
          const now = await M.api.patch("/agents/" + encodeURIComponent(a.id), body);
          done(now, "Saved." + ("handle" in body ? " The old handle @" + a.handle + " still names it as an earlier one." : ""));
        } catch (err) {
          go.disabled = false;
          status.fail("Not saved: ", said(err));
        }
      },
    },
    h("label", { for: key("name") }, "Display name"), name,
    h("label", { for: key("handle") }, "Handle"), handle,
    h("p", { class: "hint" }, HANDLE.text + " A new handle keeps the old one as an earlier name (§6.24)."),
    h("label", { for: key("git-name") }, "Git name (optional)"), gitName,
    h("label", { for: key("git-email") }, "Git email (optional)"), gitMail,
    h("p", { class: "hint" }, "The identity its commits carry, given to the agent with its resume."),
    go, status.el);
  }

  // The members of each project a profile is in, read once per project.
  async function memberViews(profiles) {
    const projects = [...new Set(profiles.flatMap((a) => (a.memberships || []).map((m) => m.project)))];
    const lists = await Promise.all(projects.map((full) => M.api.getAll("/projects/" + M.api.projectPath(full) + "/members")
      .then((r) => r.items, () => null)));
    const views = {};
    projects.forEach((full, i) => { (lists[i] || []).forEach((x) => { views[full + " " + x.id] = x; }); });
    return views;
  }

  M.views.agentsPage = async function (ctx, root, args) {
    if (ctx.me.kind !== "human") {
      append(root, h("h2", null, "Your agents"), h("p", null, "Agent profiles belong to humans."));
      return;
    }
    const wanted = args && args[0] ? args[0] : null;
    const note = h("div");
    const body = h("div", { class: "agents-page" });
    const heading = h("h2", { id: "agents-heading", tabindex: "-1" }, "Your agents");
    append(root, heading,
      h("p", { class: "hint" }, "Your agent profiles across every project: each is one identity, with its picture, its handle and the "
        + "memberships it holds. Add one to a project to make a join line there."), note, body);
    const draw = async (words) => {
      const profiles = (await M.api.getAll("/agents")).items.filter((a) => a.owner_id === ctx.me.id && !a.deleted_at);
      const views = await memberViews(profiles);
      const redraw = (answer, said) => draw(said).catch((err) => append(clear(body), h("p", { class: "send-status failed" }, "Your agents could not be read again: " + err.message)));
      clear(note);
      if (words) append(note, h("p", { class: "ok", role: "status" }, words));
      append(clear(body),
        profiles.length ? h("ul", { class: "agent-cards" }, profiles.map((a) => h("li", { class: "agent-card" + (wanted === a.id ? " wanted" : ""), "data-agent": a.id },
          h("div", { class: "agent-card-head" }, M.avatar(a, 48),
            h("h3", { class: "agent-card-title", tabindex: wanted === a.id ? "-1" : null }, a.display_name, h("span", { class: "muted" }, " @" + (a.name || a.handle)))),
          (a.memberships || []).length
            ? h("ul", { class: "agent-memberships" }, a.memberships.map((m) => membershipLine(ctx, a, m, views[m.project + " " + a.id])))
            : h("p", { class: "muted" }, "In no project yet."),
          addToProject(ctx, a),
          h("details", { class: "agent-settings", open: wanted === a.id ? true : null },
            h("summary", null, "Name, handle, picture and deletion"),
            editForm(a, redraw),
            M.pictureEditor ? M.pictureEditor(a, "/agents/" + encodeURIComponent(a.id) + "/avatar", false, redraw) : null,
            M.profileDelete ? M.profileDelete(a, redraw) : null))))
          : h("p", { class: "muted" }, "You have no agent profile yet."),
        newProfile(redraw));
      // /agents/<id> (a link to one profile): that card's title focused, once.
      const title = wanted && !words ? Array.from(body.querySelectorAll("li.agent-card.wanted .agent-card-title"))[0] : null;
      if (title) title.focus();
    };
    await draw();
  };
})(window.Maity);
