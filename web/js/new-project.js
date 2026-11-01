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
  // A table's words are getters on their index, read when drawn, so a
  // language set after the page loads applies (context/rendering.md).
  const row = (first, words, rest) => {
    const out = [first];
    Object.keys(words).forEach((at) => Object.defineProperty(out, at, { get: words[at], enumerable: true }));
    return Object.assign(out, rest);
  };
  const PRESETS = [
    row("hierarchical", { 1: () => M.t("new_project.preset.hierarchical"), 2: () => M.t("new_project.preset.hierarchical_hint") }),
    row("solo", { 1: () => M.t("new_project.preset.solo"), 2: () => M.t("new_project.preset.solo_hint") }),
  ];

  // §6.21: the providers, Keep the Why preselected, and the setup options
  // with their cards' titles verbatim, in the cards' order; the Keep the Why
  // ones only under Keep the Why. All five come ticked; each is sent as true
  // or false.
  const PROVIDERS = [
    row("keep-the-why", { 1: () => M.t("new_project.provider.keep_the_why") }),
    row("none", { 1: () => M.t("new_project.provider.none") }),
  ];
  const OPTIONS = [
    row("keep_the_why_init", { 1: () => M.t("new_project.option.keep_the_why_init") }, { 2: true }),
    row("keep_the_why_badge", { 1: () => M.t("new_project.option.keep_the_why_badge") }, { 2: true }),
    row("keep_the_why_ci", { 1: () => M.t("new_project.option.keep_the_why_ci") }, { 2: true }),
    row("keep_the_why_dashboard", { 1: () => M.t("new_project.option.keep_the_why_dashboard") }, { 2: true }),
    row("maity_badge", { 1: () => M.t("new_project.option.maity_badge") }, { 2: false }),
  ];
  // §6.21 `dashboard_path`: as the hub checks it, one to five segments of
  // [a-z0-9][a-z0-9._-]{0,62} joined by "/", no leading or trailing slash, and
  // ".." nowhere in the value (a segment alone never is "..", so the rule means a..b too).
  const DASHBOARD_PATH_DEFAULT = "keep-the-why-dashboard";
  const DASHBOARD_PATH = /^[a-z0-9][a-z0-9._-]{0,62}(\/[a-z0-9][a-z0-9._-]{0,62}){0,4}$/;
  const dashboardPathOk = (v) => DASHBOARD_PATH.test(v) && !v.includes("..");

  // The hub's reasons, in words; any other reason is shown as it comes.
  const REASONS = {
    taken: () => M.t("new_project.reason.taken"),
    reserved: () => M.t("new_project.reason.reserved"),
    string_pattern_mismatch: () => M.dom.NAME_RULES.slug.text,
    string_too_short: () => M.t("new_project.reason.required"),
    string_too_long: () => M.t("new_project.reason.too_long"),
    missing: () => M.t("new_project.reason.required"),
    not_a_configured_forge: () => M.FORGE_RULE,
    unknown: () => M.t("new_project.reason.unknown"),
    // owner: the same answer for every handle that is no organisation of one's own.
    owner_unknown: () => M.t("new_project.reason.owner_unknown"),
    unknown_provider: () => M.t("new_project.reason.unknown_provider"),
    not_a_boolean: () => M.t("new_project.reason.not_a_boolean"),
    format: () => M.t("new_project.path.rule"),
  };
  const reasonWords = (reason) => (Object.hasOwn(REASONS, reason) ? REASONS[reason]() : null);

  // A slug proposed from the name until the slug field is typed in.
  function slugFrom(name) {
    return name.toLowerCase().normalize("NFKD").replace(/[̀-ͯ]/g, "")
      .replace(/[^a-z0-9]+/g, "-").replace(/^-+/, "").replace(/-+$/, "").slice(0, 63).replace(/-+$/, "");
  }

  // Project settings name them the same way (js/app.js).
  M.projectSetup = { PROVIDERS, OPTIONS, DASHBOARD_PATH_DEFAULT };

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
    const owner = field("project-owner", M.t("new_project.owner"),
      h("select", { id: "project-owner" },
        h("option", { value: "" }, M.t("new_project.owner.you", { handle: ctx.me.handle })),
        orgs.map((o) => h("option", { value: o.handle }, "@" + o.handle + " · " + o.display_name))),
      M.t("new_project.owner.hint"));
    owner.input.value = "";
    const name = field("project-name", M.t("new_project.name"), h("input", { id: "project-name", required: true, maxlength: "200", autocomplete: "off" }));
    const slug = field("project-slug", M.t("new_project.slug"),
      h("input", { id: "project-slug", required: true, pattern: SLUG_PATTERN, maxlength: "63", autocomplete: "off", spellcheck: "false" }),
      M.dom.NAME_RULES.slug.text + " " + M.t("new_project.slug.hint"));
    const repository = field("project-repository", M.t("new_project.repository"),
      h("input", { id: "project-repository", type: "url", placeholder: "https://github.com/owner/name", autocomplete: "off" }));
    // §16.9, §6.1: public by default for the namespace owner; anyone else's
    // project starts private, and only an owner can make it public.
    const privateBox = h("input", { id: "project-private", type: "checkbox", "aria-describedby": "project-private-hint project-private-repo" });
    const privateHint = h("p", { class: "hint", id: "project-private-hint" });
    const showPrivate = () => {
      const org = orgs.find((o) => o.handle === owner.input.value);
      const fixed = !!org && org.my_role !== "owner";
      privateBox.checked = fixed || (privateBox.disabled ? false : privateBox.checked);
      privateBox.disabled = fixed;
      privateHint.textContent = fixed ? M.t("new_project.private.fixed") : M.t("new_project.private.hint");
    };
    owner.input.addEventListener("change", showPrivate);
    showPrivate();
    const privateField = h("div", { class: "project-private" },
      h("label", { class: "check", for: "project-private" }, privateBox, " " + M.t("new_project.private.label")),
      privateHint,
      h("p", { class: "hint", id: "project-private-repo" }, M.t("new_project.private.repository")));
    const memory = field("project-memory", M.t("new_project.memory"),
      h("select", { id: "project-memory" }, PROVIDERS.map(([value, label]) => h("option", { value, selected: value === "keep-the-why" }, label))),
      M.t("new_project.memory.hint"));
    memory.input.value = "keep-the-why";
    // The options, each a checkbox ticked to begin with.
    // What an option does beyond its card is said right under it, read
    // before it is ticked (the designer's pass part 3).
    const NOTES = {
      maity_badge: M.t("new_project.option.maity_badge_note"),
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
    const pathField = h("div", { class: "setup-path field-stack" },
      h("label", { for: "setup-dashboard-path" }, M.t("new_project.path")), pathInput,
      h("p", { class: "hint", id: "setup-dashboard-path-hint" }, M.t("new_project.path.hint")),
      pathError);
    dashboard.row = h("div", { class: "check-row" }, dashboard.row, pathField);
    const showPath = () => { pathField.hidden = !dashboard.box.checked; };
    dashboard.box.addEventListener("change", showPath);
    const setupError = h("p", { class: "field-error", id: "project-setup-error", role: "alert" });
    const setupBox = h("fieldset", { class: "project-setup", "aria-describedby": "project-setup-hint project-setup-error" },
      h("legend", null, M.t("new_project.setup")),
      options.map((o) => o.row),
      h("p", { class: "hint", id: "project-setup-hint" }, M.t("new_project.setup.hint")),
      setupError);
    const showOptions = () => {
      const ktwChosen = memory.input.value === "keep-the-why";
      options.forEach((o) => { if (o.ktwOnly) o.row.hidden = !ktwChosen; });
    };
    memory.input.addEventListener("change", showOptions);
    const preset = field("project-preset", M.t("new_project.preset"),
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
        const text = (key === "owner" && reasonWords("owner_" + reason)) || reasonWords(reason) || reason;
        if (key === "setup.dashboard_path") {
          pathError.textContent = text;
          pathInput.setAttribute("aria-invalid", "true");
          return;
        }
        const option = options.find((o) => key === "setup." + o.key);
        if (option || key === "setup") {
          setupError.textContent += (setupError.textContent ? " " : "") + (option ? M.t("new_project.field_reason", { field: OPTIONS.find(([k]) => k === option.key)[1], reason: text }) : text);
          return;
        }
        const target = byField[key];
        if (!target) { rest.push(M.t("new_project.field_reason", { field: key, reason: text })); return; }
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
        // Left out unless private: the hub's default and its look at the repository decide (§6.1).
        if (privateBox.checked) body.public_page = "off";
        body.memory = { provider: memory.input.value };
        // §6.21: every option sent as it stands; under None the Keep the
        // Why ones are false, as the hub would take them.
        body.setup = Object.fromEntries(options.map((o) => [o.key, o.box.checked && !(o.ktwOnly && body.memory.provider !== "keep-the-why")]));
        // The path only with the dashboard chosen; otherwise left out, not sent as null.
        if (sendsPath) body.setup.dashboard_path = pathInput.value.trim();
        body.policy = { preset: preset.input.value };
        status.busy(M.t("new_project.creating"));
        submit.disabled = true;
        try {
          const created = await M.api.post("/projects", body);
          status.done();
          // What the hub made of it, said once on the page that follows.
          M.projectCreated = { full_name: created.full_name, public_page: created.public_page };
          // A new project has nothing waiting yet; its next step is to
          // join an agent, which the Agents view offers when it is empty.
          M.route.go(ctx.projectLink(created.full_name, "agents"));
        } catch (err) {
          submit.disabled = false;
          const fields = err.code === "invalid" && err.details && err.details.fields ? err.details.fields : null;
          if (fields) {
            const rest = showErrors(fields);
            if (rest.length) status.fail(M.t("new_project.not_created"), { message: rest.join("; ") });
            else status.done();
          } else if (err.code === "forbidden" && err.details && err.details.reason === "org_role") {
            status.fail(M.t("new_project.not_created"), { message: M.t("new_project.refused.org_role") });
          } else if (err.code === "forbidden" && err.details && err.details.reason === "moderation_hold") {
            status.fail(M.t("new_project.not_created"), { message: M.t("new_project.refused.moderation_hold") });
          } else {
            status.fail(M.t("new_project.not_created"), err);
          }
        }
      },
    },
    orgs.length ? owner.nodes : null,
    name.nodes, slug.nodes, repository.nodes,
    privateField,
    memory.nodes,
    setupBox,
    preset.nodes);
    const submit = h("button", { type: "submit", class: "primary" }, M.t("new_project.submit"));
    append(form, submit, status.el);

    append(root, h("h2", null, M.t("new_project.title")),
      h("p", { class: "muted" }, M.t("new_project.intro")),
      form);
    name.input.focus();
  };

  // A human with no membership yet: the one thing to do is create a project.
  M.views.noProjects = function (ctx, root) {
    append(clear(root), h("div", { class: "empty-state" },
      h("h2", null, M.t("new_project.none.title")),
      h("p", null, M.t("new_project.none.text")),
      h("p", null, h("a", { class: "button", href: "/new" }, M.t("new_project.none.create")))));
  };
})(window.Maity);
