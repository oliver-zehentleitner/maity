// Create a project (docs/api.md §6.1, POST /projects): slug, name, an
// optional repository, the project memory with its setup options (§6.21),
// and the policy preset, and where the hub takes it the owner: the human or
// one of their organisations (§6.26). The creator
// becomes its owner; on 201 the page switches to the new project's Agents
// view. The hub's `invalid` answer is shown next to the fields it names.
// Also the empty state of a human without memberships.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;

  // docs/api.md, "Conventions": projects are addressed by this slug. The
  // hyphen is escaped: browsers compile `pattern` with the v flag, where an
  // unescaped "-" in a class is a syntax error and the pattern is dropped.
  const SLUG_PATTERN = M.dom.NAME_RULES.slug.pattern;
  const SLUG = M.dom.NAME_RULES.slug.test;

  // The preset's name is the option; what it means is the hint under the
  // select, which follows the choice (the designer's pass part 3: a long
  // option was cut off in the select).
  const PRESETS = [
    ["hierarchical", "Hierarchical", "Reviewers move cards to done, admins arbitrate contracts."],
    ["solo", "Solo", "The holder moves its own card to done, the owner arbitrates."],
  ];

  // §6.21: the providers, Keep the Why preselected, and the setup options
  // with their cards' titles verbatim, in the cards' order; the Keep the Why
  // ones only under Keep the Why. All five come ticked; each is sent as true
  // or false.
  const PROVIDERS = [["keep-the-why", "Keep the Why"], ["none", "None"]];
  const OPTIONS = [
    ["keep_the_why_init", "Set up Keep the Why in the repository", true],
    ["keep_the_why_badge", "Add the Keep the Why badge to the README", true],
    ["keep_the_why_ci", "Run the Keep the Why linter in CI", true],
    ["keep_the_why_dashboard", "Publish the Keep the Why dashboard", true],
    ["maity_badge", "Add the Maity badge to the README", false],
  ];
  // §6.21 `dashboard_path`: as the hub checks it, one to five segments of
  // [a-z0-9][a-z0-9._-]{0,62} joined by "/", no leading or trailing slash, and
  // ".." nowhere in the value (a segment alone never is "..", so the rule means a..b too).
  const DASHBOARD_PATH_DEFAULT = "keep-the-why-dashboard";
  const DASHBOARD_PATH = /^[a-z0-9][a-z0-9._-]{0,62}(\/[a-z0-9][a-z0-9._-]{0,62}){0,4}$/;
  const dashboardPathOk = (v) => DASHBOARD_PATH.test(v) && !v.includes("..");
  const DASHBOARD_PATH_RULE = "One to five parts joined by /, each starting with a lowercase letter or a digit, "
    + "then lowercase letters, digits, dots, hyphens or underscores; no / at either end, no .. anywhere";

  // The hub's reasons, in words; any other reason is shown as it comes.
  const REASONS = {
    taken: "This owner has a project with this slug already, or had one by that name.",
    reserved: "This word is part of the dashboard's addresses; choose another slug.",
    string_pattern_mismatch: M.dom.NAME_RULES.slug.text,
    string_too_short: "Required.",
    string_too_long: "Too long.",
    missing: "Required.",
    not_a_configured_forge: M.FORGE_RULE,
    unknown: "Not a known value.",
    // owner: the same answer for every handle that is no organisation of one's own.
    owner_unknown: "Not an organisation you are in.",
    unknown_provider: "Not a memory provider this hub knows.",
    not_a_boolean: "Must be ticked or not.",
    format: DASHBOARD_PATH_RULE,
  };

  // A slug proposed from the name until the slug field is typed in.
  function slugFrom(name) {
    return name.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").replace(/-+$/, "").slice(0, 63).replace(/-+$/, "");
  }

  // Project settings name them the same way (js/app.js).
  // The project just created and its page's value from the 201, said once
  // on the next view of that project.
  let created = null;
  const takeCreated = (full) => {
    if (!created || created.full_name !== full) return null;
    const said = created;
    created = null;
    return said;
  };
  M.projectSetup = { PROVIDERS, OPTIONS, DASHBOARD_PATH_DEFAULT, takeCreated };

  M.views.newProject = async function (ctx, root) {
    const field = (id, label, input, hint) => {
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      input.setAttribute("aria-describedby", (hint ? id + "-hint " : "") + id + "-error");
      return { input, error, nodes: [h("label", { for: id }, label), input, hint ? h("p", { class: "hint", id: id + "-hint" }, hint) : null, error] };
    };

    // §6.26: the owner, where the human is in an organisation that lets
    // them create projects; otherwise not offered. A suspended organisation
    // takes no new project.
    const orgs = await M.api.get("/orgs").then((r) => r.items.filter((o) => !o.moderation && (o.my_role !== "member" || o.members_create_projects))).catch(() => []);
    const owner = field("project-owner", "Owner",
      h("select", { id: "project-owner" },
        h("option", { value: "" }, "@" + ctx.me.handle + " (you)"),
        orgs.map((o) => h("option", { value: o.handle }, "@" + o.handle + " · " + o.display_name))),
      "The project's address is <owner>/<slug>. An organisation's owners hold trust owner in every project it owns.");
    owner.input.value = "";
    const name = field("project-name", "Name", h("input", { id: "project-name", required: true, maxlength: "200", autocomplete: "off" }));
    const slug = field("project-slug", "Slug",
      h("input", { id: "project-slug", required: true, pattern: SLUG_PATTERN, maxlength: "63", autocomplete: "off", spellcheck: "false" }),
      M.dom.NAME_RULES.slug.text + " Used in links and by the CLI; it cannot be changed later.");
    const repository = field("project-repository", "Repository (optional)",
      h("input", { id: "project-repository", type: "url", placeholder: "https://github.com/owner/name", autocomplete: "off" }),
      M.t("newproject.repository.private_note"));
    // §16.9: a project is public by default for the namespace's owner; anyone
    // else creating in an organisation creates it private, fixed, and an
    // owner of the organisation may make it public later.
    const privateBox = h("input", { type: "checkbox", id: "project-private", "aria-describedby": "project-private-hint" });
    const privateHint = h("p", { class: "hint", id: "project-private-hint" });
    const ownsNamespace = () => !owner.input.value || orgs.some((o) => o.handle === owner.input.value && o.my_role === "owner");
    const settlePrivate = () => {
      const fixed = !ownsNamespace();
      if (fixed) privateBox.checked = true;
      else if (privateBox.disabled) privateBox.checked = false;
      privateBox.disabled = fixed;
      privateHint.textContent = fixed ? M.t("newproject.private.fixed") : M.t("newproject.private.hint");
    };
    owner.input.addEventListener("change", settlePrivate);
    settlePrivate();
    const visibility = [h("label", { class: "check", for: "project-private" }, privateBox, " ", M.t("newproject.private")), privateHint];
    const memory = field("project-memory", "Project memory",
      h("select", { id: "project-memory" }, PROVIDERS.map(([value, label]) => h("option", { value, selected: value === "keep-the-why" }, label))),
      "Where the project keeps its decisions and their reasons. Maity stores none of it: an agent sets it up in the repository, "
      + "through the setup cards below, each a pull request.");
    memory.input.value = "keep-the-why";
    // The options, each a checkbox ticked to begin with.
    // What an option does beyond its card is said right under it, read
    // before it is ticked (the designer's pass part 3).
    const NOTES = {
      maity_badge: "It also switches the project's badge on from the start: it shows anyone how many humans and agents "
        + "the project has. Project settings switch it off.",
    };
    const options = OPTIONS.map(([key, label, ktwOnly]) => {
      const note = NOTES[key] ? h("span", { class: "check-note muted", id: "setup-" + key + "-note" }, NOTES[key]) : null;
      const box = h("input", { id: "setup-" + key, type: "checkbox", checked: true, "aria-describedby": note ? "setup-" + key + "-note" : null });
      box.checked = true;
      const check = h("label", { class: "check", for: "setup-" + key }, box, " " + label);
      return { key, ktwOnly, box, row: note ? h("div", { class: "check-row" }, check, note) : check };
    });
    // The dashboard's path, under its option, while it is ticked (§6.21).
    const dashboard = options.find((o) => o.key === "keep_the_why_dashboard");
    const pathInput = h("input", { id: "setup-dashboard-path", value: DASHBOARD_PATH_DEFAULT, autocomplete: "off", spellcheck: "false",
      "aria-describedby": "setup-dashboard-path-hint setup-dashboard-path-error" });
    pathInput.value = DASHBOARD_PATH_DEFAULT;
    const pathError = h("p", { class: "field-error", id: "setup-dashboard-path-error", role: "alert" });
    const pathField = h("div", { class: "setup-path" },
      h("label", { for: "setup-dashboard-path" }, "Path"), pathInput,
      h("p", { class: "hint", id: "setup-dashboard-path-hint" }, "Where the dashboard is published, below the root of the repository's "
        + "documentation site. " + DASHBOARD_PATH_RULE + "."),
      pathError);
    dashboard.row = h("div", { class: "check-row" }, dashboard.row, pathField);
    const showPath = () => { pathField.hidden = !dashboard.box.checked; };
    dashboard.box.addEventListener("change", showPath);
    const setupError = h("p", { class: "field-error", id: "project-setup-error", role: "alert" });
    const setupBox = h("fieldset", { class: "project-setup", "aria-describedby": "project-setup-hint project-setup-error" },
      h("legend", null, "Setup cards"),
      options.map((o) => o.row),
      h("p", { class: "hint", id: "project-setup-hint" }, "Each ticked option becomes a card for an agent once the project has a repository "
        + "(now, or when it is set later)."),
      setupError);
    const showOptions = () => {
      const ktwChosen = memory.input.value === "keep-the-why";
      options.forEach((o) => { if (o.ktwOnly) o.row.hidden = !ktwChosen; });
    };
    memory.input.addEventListener("change", showOptions);
    const preset = field("project-preset", "Policy preset",
      h("select", { id: "project-preset" }, PRESETS.map(([value, label]) => h("option", { value }, label))), PRESETS[0][2]);
    const presetHint = preset.nodes[2];
    preset.input.addEventListener("change", () => {
      const chosen = PRESETS.find(([value]) => value === preset.input.value);
      presetHint.textContent = chosen ? chosen[2] : "";
    });

    let slugTyped = false;
    slug.input.addEventListener("input", () => { slugTyped = slug.input.value !== ""; });
    name.input.addEventListener("input", () => {
      if (!slugTyped) slug.input.value = slugFrom(name.input.value);
    });

    // The hub's field names (details.fields) to the inputs they belong to.
    const byField = { owner, name, slug, repository, "repository.url": repository, policy: preset, "policy.preset": preset,
      memory, "memory.provider": memory };
    const all = [owner, name, slug, repository, memory, preset];
    const status = M.statusLine();

    const showErrors = (fields) => {
      all.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
      setupError.textContent = "";
      pathError.textContent = "";
      pathInput.removeAttribute("aria-invalid");
      const rest = [];
      Object.keys(fields).forEach((key) => {
        const reason = String(fields[key]);
        const text = (key === "owner" && REASONS["owner_" + reason]) || REASONS[reason] || reason;
        if (key === "setup.dashboard_path") {
          pathError.textContent = text;
          pathInput.setAttribute("aria-invalid", "true");
          return;
        }
        const option = options.find((o) => key === "setup." + o.key);
        if (option || key === "setup") {
          setupError.textContent += (setupError.textContent ? " " : "") + (option ? OPTIONS.find(([k]) => k === option.key)[1] + ": " : "") + text;
          return;
        }
        const target = byField[key];
        if (!target) { rest.push(key + ": " + text); return; }
        target.error.textContent = text;
        target.input.setAttribute("aria-invalid", "true");
      });
      const first = all.find((f) => f.input.getAttribute("aria-invalid") === "true");
      if (first) first.input.focus();
      else if (pathInput.getAttribute("aria-invalid") === "true") pathInput.focus();
      return rest;
    };

    const form = h("form", {
      class: "project-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const body = { slug: slug.input.value.trim(), name: name.input.value.trim() };
        if (owner.input.value) body.owner = owner.input.value;
        const local = {};
        if (!body.name) local.name = "string_too_short";
        if (!SLUG.test(body.slug)) local.slug = body.slug ? "string_pattern_mismatch" : "string_too_short";
        const sendsPath = memory.input.value === "keep-the-why" && dashboard.box.checked;
        if (sendsPath && !dashboardPathOk(pathInput.value.trim())) local["setup.dashboard_path"] = "format";
        if (Object.keys(local).length) { showErrors(local); status.done(); return; }
        showErrors({});
        const url = repository.input.value.trim();
        if (url) body.repository = { url };
        // Only a ticked Private is sent; otherwise the hub's default stands.
        if (privateBox.checked) body.public_page = "off";
        body.memory = { provider: memory.input.value };
        // §6.21: every option sent as it stands; under None the Keep the
        // Why ones are false, as the hub would take them.
        body.setup = Object.fromEntries(options.map((o) => [o.key, o.box.checked && !(o.ktwOnly && body.memory.provider !== "keep-the-why")]));
        // The path only with the dashboard chosen; otherwise left out, not sent as null.
        if (sendsPath) body.setup.dashboard_path = pathInput.value.trim();
        body.policy = { preset: preset.input.value };
        status.busy("Creating…");
        submit.disabled = true;
        try {
          const made = await M.api.post("/projects", body);
          created = { full_name: made.full_name, public_page: made.public_page };
          status.done();
          // A new project has nothing waiting yet; its next step is to
          // join an agent, which the Agents view offers when it is empty.
          M.route.go(ctx.projectLink(made.full_name, "agents"));
        } catch (err) {
          submit.disabled = false;
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields) {
            const rest = showErrors(fields);
            if (rest.length) status.fail("Not created: ", { message: rest.join("; ") });
            else status.done();
          } else if (err.code === "forbidden" && err.details && err.details.reason === "org_role") {
            status.fail("Not created: ", { message: "this organisation lets only its owners and admins create projects" });
          } else if (err.code === "forbidden" && err.details && err.details.reason === "moderation_hold") {
            status.fail("Not created: ", { message: "this organisation is suspended and takes no new project" });
          } else {
            status.fail("Not created: ", err);
          }
        }
      },
    },
    orgs.length ? owner.nodes : null,
    name.nodes, slug.nodes, repository.nodes,
    visibility,
    memory.nodes,
    setupBox,
    preset.nodes);
    const submit = h("button", { type: "submit", class: "primary" }, "Create project");
    append(form, submit, status.el);

    append(root, h("h2", null, "Create a project"),
      h("p", { class: "muted" }, "You become its owner. Agents join it afterwards, from its Agents view (Join an agent)."),
      form);
    name.input.focus();
  };

  // A human with no membership yet: the one thing to do is create a project.
  M.views.noProjects = function (ctx, root) {
    append(clear(root), h("div", { class: "empty-state" },
      h("h2", null, "No projects yet"),
      h("p", null, "You are not a member of any project. Create one; you become its owner and can then join agents to it."),
      h("p", null, h("a", { class: "button", href: "/new" }, "Create a project"))));
  };
})(window.Maity);
