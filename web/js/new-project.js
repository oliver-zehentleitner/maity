// Create a project (docs/api.md §6.1, POST /projects): slug, name, an
// optional repository, the project memory with its setup options (§6.21),
// and the policy preset. The creator
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

  const PRESETS = [
    ["hierarchical", "Hierarchical: reviewers move cards to done, admins arbitrate contracts"],
    ["solo", "Solo: the holder moves its own card to done, the owner arbitrates"],
  ];

  // §6.21: the providers, Keep the Why preselected, and the setup options
  // with their cards' titles verbatim; the Keep the Why ones only under
  // Keep the Why. All three come ticked; each is sent as true or false.
  const PROVIDERS = [["keep-the-why", "Keep the Why"], ["none", "None"]];
  const OPTIONS = [
    ["keep_the_why_init", "Set up Keep the Why in the repository", true],
    ["keep_the_why_badge", "Add the Keep the Why badge to the README", true],
    ["maity_badge", "Add the Maity badge to the README", false],
  ];

  // The hub's reasons, in words; any other reason is shown as it comes.
  const REASONS = {
    taken: "A project with this slug exists.",
    string_pattern_mismatch: M.dom.NAME_RULES.slug.text,
    string_too_short: "Required.",
    string_too_long: "Too long.",
    missing: "Required.",
    not_a_configured_forge: M.FORGE_RULE,
    unknown: "Not a known value.",
    unknown_provider: "Not a memory provider this hub knows.",
    not_a_boolean: "Must be ticked or not.",
  };

  // A slug proposed from the name until the slug field is typed in.
  function slugFrom(name) {
    return name.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").replace(/-+$/, "").slice(0, 63).replace(/-+$/, "");
  }

  // Project settings name them the same way (js/app.js).
  M.projectSetup = { PROVIDERS, OPTIONS };

  M.views.newProject = async function (ctx, root) {
    // Memory and setup where the hub takes them (§6.21); an older hub
    // refuses a field it does not know, so then they are not offered.
    // A hub before §6.21 knows the provider only as keep_the_why: the
    // dropdown then sends that alias, without setup options.
    let fieldsRead = true;
    const fields = await M.api.hubBody("POST", "/projects").catch(() => { fieldsRead = false; return new Set(); });
    const knowsMemory = fields.has("memory") && fields.has("setup");
    const knowsAlias = !knowsMemory && fields.has("keep_the_why");
    const field = (id, label, input, hint) => {
      const error = h("p", { class: "field-error", id: id + "-error", role: "alert" });
      input.setAttribute("aria-describedby", (hint ? id + "-hint " : "") + id + "-error");
      return { input, error, nodes: [h("label", { for: id }, label), input, hint ? h("p", { class: "hint", id: id + "-hint" }, hint) : null, error] };
    };

    const name = field("project-name", "Name", h("input", { id: "project-name", required: true, maxlength: "200", autocomplete: "off" }));
    const slug = field("project-slug", "Slug",
      h("input", { id: "project-slug", required: true, pattern: SLUG_PATTERN, maxlength: "63", autocomplete: "off", spellcheck: "false" }),
      M.dom.NAME_RULES.slug.text + " Used in links and by the CLI; it cannot be changed later.");
    const repository = field("project-repository", "Repository (optional)",
      h("input", { id: "project-repository", type: "url", placeholder: "https://github.com/owner/name", autocomplete: "off" }));
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
      h("select", { id: "project-preset" }, PRESETS.map(([value, label]) => h("option", { value }, label))));

    let slugTyped = false;
    slug.input.addEventListener("input", () => { slugTyped = slug.input.value !== ""; });
    name.input.addEventListener("input", () => {
      if (!slugTyped) slug.input.value = slugFrom(name.input.value);
    });

    // The hub's field names (details.fields) to the inputs they belong to.
    const byField = { name, slug, repository, "repository.url": repository, policy: preset, "policy.preset": preset,
      memory, "memory.provider": memory, keep_the_why: memory };
    const all = [name, slug, repository, memory, preset];
    const status = M.statusLine();

    const showErrors = (fields) => {
      all.forEach((f) => { f.error.textContent = ""; f.input.removeAttribute("aria-invalid"); });
      setupError.textContent = "";
      const rest = [];
      Object.keys(fields).forEach((key) => {
        const reason = String(fields[key]);
        const text = REASONS[reason] || reason;
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
      return rest;
    };

    const form = h("form", {
      class: "project-form",
      novalidate: true,
      onsubmit: async (e) => {
        e.preventDefault();
        const body = { slug: slug.input.value.trim(), name: name.input.value.trim() };
        const local = {};
        if (!body.name) local.name = "string_too_short";
        if (!SLUG.test(body.slug)) local.slug = body.slug ? "string_pattern_mismatch" : "string_too_short";
        if (Object.keys(local).length) { showErrors(local); status.done(); return; }
        showErrors({});
        const url = repository.input.value.trim();
        if (url) body.repository = { url };
        if (knowsAlias) body.keep_the_why = memory.input.value === "keep-the-why";
        if (knowsMemory) {
          body.memory = { provider: memory.input.value };
          // §6.21: every option sent as it stands; under None the Keep the
          // Why ones are false, as the hub would take them.
          body.setup = Object.fromEntries(options.map((o) => [o.key, o.box.checked && !(o.ktwOnly && body.memory.provider !== "keep-the-why")]));
        }
        body.policy = { preset: preset.input.value };
        status.busy("Creating…");
        submit.disabled = true;
        try {
          const created = await M.api.post("/projects", body);
          status.done();
          // A new project has nothing waiting yet; its next step is to
          // join an agent, which the Agents view offers when it is empty.
          window.location.hash = ctx.projectLink(created.slug, "agents");
        } catch (err) {
          submit.disabled = false;
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields) {
            const rest = showErrors(fields);
            if (rest.length) status.fail("Not created: ", { message: rest.join("; ") });
            else status.done();
          } else {
            status.fail("Not created: ", err);
          }
        }
      },
    },
    name.nodes, slug.nodes, repository.nodes,
    knowsMemory || knowsAlias ? memory.nodes : null,
    knowsMemory ? setupBox : null,
    // What the hub chooses is said where its machine form could not be read.
    fieldsRead ? null : h("p", { class: "hint" }, "Project memory: this hub's machine form could not be read, so its defaults apply."),
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
      h("p", null, h("a", { class: "button", href: "#/new" }, "Create a project"))));
  };
})(window.Maity);
