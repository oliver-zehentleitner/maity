// The fetch layer. Answers from /api/v1/... (docs/api.md) or, on a page
// opened from the file system only, from the fixtures in fixtures/
// (bundled into fixtures/fixtures.js). On an http(s) origin there is no
// way into fixture mode and the bundle is never loaded: see
// context/fixtures.md.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const API_BASE = "/api/v1";

  const params = new URLSearchParams(window.location.search);

  const source = window.location.protocol === "file:" ? "fixtures" : "api";

  class ApiError extends Error {
    constructor(message, status, path, code, details) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.path = path;
      this.code = code || null;
      this.details = details || {};
    }
  }

  // ---- fixture mode -------------------------------------------------------

  // A deep copy, so that writes in fixture mode change this page load only.
  let store = null;
  // ?signed_out=1 starts fixture mode without a session, to show the login.
  let fixtureSignedIn = params.get("signed_out") !== "1";
  // The device code of §2.6.2 this tab made, and a mailed code asked for (§2.6.3).
  let deviceSim = null;
  let deviceSerial = 0;
  let mailPending = false;
  let mailNext = "/";
  function deviceOf(id, path) {
    if (!deviceSim || deviceSim.id !== id) fail(404, "not_found", "Not found", path);
    if (["waiting", "redeemed"].includes(deviceSim.status) && Date.parse(deviceSim.expires_at) <= Date.now()) deviceSim.status = "expired";
    return deviceSim;
  }
  function deviceView(d) {
    const view = { id: d.id, status: d.status, expires_at: d.expires_at };
    if (d.device) view.device = d.device;
    if (d.status === "redeemed") view.choices = [18, d.match, 83];
    return view;
  }
  let fixturePassword = null;
  // ?no_projects=1 starts it with no memberships, to show the empty state.
  const fixtureNoProjects = params.get("no_projects") === "1";
  // ?ktw=unavailable: the root .keep-the-why cannot be read; ?ktw=member_failed:
  // one family member's read fails (docs/api.md §11.3).
  const fixtureKtw = params.get("ktw");
  // ?as=<member id>: the mock takes member changes (PATCH and DELETE of a
  // membership) as coming from that member, to show how the hub answers an
  // admin agent (§2.3 ᵃ); the page itself stays the signed-in human's.
  const fixtureAs = params.get("as");

  // The bundle is loaded on the first fixture request, never on an
  // http(s) origin (it is not referenced from index.html).
  let loading = null;
  function loadFixtures() {
    if (window.MAITY_FIXTURES) return Promise.resolve();
    if (!loading) {
      loading = new Promise((resolve, reject) => {
        const script = document.createElement("script");
        script.src = "fixtures/fixtures.js";
        script.addEventListener("load", () => resolve());
        script.addEventListener("error", () => reject(new ApiError("fixtures/fixtures.js could not be loaded", 0, "")));
        document.head.appendChild(script);
      });
    }
    return loading;
  }

  function fixtures() {
    if (store) return store;
    if (!window.MAITY_FIXTURES) {
      throw new ApiError("fixtures/fixtures.js is not loaded", 0, "");
    }
    store = JSON.parse(JSON.stringify(window.MAITY_FIXTURES));
    if (fixtureNoProjects) store["me.json"].projects = [];
    return store;
  }

  function nowIso() {
    return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
  }

  let counter = 0;
  function localId(prefix) {
    counter += 1;
    return prefix + "-local-" + counter;
  }

  function fail(status, code, message, path, details) {
    throw new ApiError(message, status, path, code, details);
  }

  // A project's path from its full name (§6.25): `<owner>/<slug>`, each
  // part encoded, the slash between them kept.
  const projectPath = (full) => String(full).split("/").map(encodeURIComponent).join("/");
  // Fixture mode keeps a project in fixtures/<slug>/; its full name is the
  // project view's, else its owner's handle as the fixtures name it.
  const FIXTURE_OWNERS = { guestlab: "guest" };
  const fixtureSlug = (full) => String(full).split("/").pop();
  function fullOf(slug) {
    const view = fixtures()[slug + "/project.json"];
    return (view && view.full_name) || (FIXTURE_OWNERS[slug] || me().member.handle) + "/" + slug;
  }
  const fixtureSlugs = () => [...new Set(Object.keys(fixtures()).filter((k) => k.includes("/")).map((k) => k.split("/")[0]))];
  // The fixture directory a full name (or one of its aliases) names, or null.
  function slugOfFull(full) {
    return fixtureSlugs().find((slug) => fullOf(slug) === full
      || ((fixtures()[slug + "/project.json"] || {}).aliases || []).includes(full)) || null;
  }
  // §6.25: at most 8 earlier names, and 3 renames and transfers a day.
  const nameChanges = {};
  // `full`: the name it would have; taking back one's own earlier name
  // adds none, so the limit does not stop it (as the hub, #487).
  function renameCheck(p, path, full) {
    if ((p.aliases || []).length >= 8 && !(p.aliases || []).includes(full)) fail(409, "alias_limit", "at most 8 earlier names", path, { limit: 8, aliases: p.aliases });
    const day = (nameChanges[p.id] || []).filter((t) => Date.now() - t < 86400000);
    if (day.length >= 3) fail(429, "rate_limited", "at most 3 renames and transfers a day", path);
  }
  function renamed(p, full) {
    // A name taken back is current again, no longer an earlier one.
    p.aliases = (p.aliases || []).filter((x) => x !== full).concat(p.full_name);
    p.full_name = full;
    (nameChanges[p.id] = nameChanges[p.id] || []).push(Date.now());
  }
  // The words that follow a project in a route (§6.25): never a slug.
  const ROUTE_WORDS = ["agents", "attachments", "banner", "contracts", "conversations", "credentials", "events", "forge", "group-chats",
    "invitations", "joins", "jour-fixe", "keep-the-why", "logo", "members", "memory", "messages", "placements", "probe", "releases",
    "requests", "rules", "runners", "swarm", "takeovers", "tasks", "ticker", "transfer"];
  // /projects/{owner}/{slug}/… reads the fixture of that full name; an old
  // one-segment path (/projects/maity/tasks) is refused as the hub refuses
  // it (410), never routed to another project.
  function namespaced(path, fullPath) {
    const m = /^\/projects\/([^/]+)(?:\/([^/]+))?(\/.*)?$/.exec(path);
    if (!m) return path;
    const first = decodeURIComponent(m[1]);
    const slug = m[2] ? slugOfFull(first + "/" + decodeURIComponent(m[2])) : null;
    if (slug) return "/projects/" + slug + (m[3] || "");
    if (!m[2] || fixtureSlugs().includes(first)) fail(410, "project_path_outdated", "this address of a project is no longer served", fullPath);
    return fail(404, "not_found", "Not found", fullPath);
  }

  // A project's placements (fixtures/<slug>/placements.json, §15.5), none
  // where the fixture has none; one of them, if the caller may steer it.
  function placementsOf(slug) {
    const data = fixtures();
    if (!data[slug + "/placements.json"]) data[slug + "/placements.json"] = { items: [], next_cursor: null };
    return data[slug + "/placements.json"].items;
  }
  function placementFor(slug, id, path) {
    project(slug, path);
    const p = placementsOf(slug).find((x) => x.id === id && x.active);
    if (!p) fail(404, "not_found", "Not found", path);
    const runner = runnersFile().items.find((r) => r.id === p.runner.id);
    const admin = me().member.kind === "human" && ["owner", "admin"].includes(trustIn(slug)) && runner && runner.owner_id === me().member.id;
    const profile = (fixtures()[slug + "/members.json"] || { items: [] }).items.find((x) => x.id === p.agent.id);
    if (!admin && !(profile && profile.owner_id === me().member.id)) fail(403, "forbidden", "members:admin and the runner, or the agent's owner", path);
    return p;
  }

  // The fixture of one project: fixtures/<slug>/<name>.json.
  function file(slug, name, path) {
    const data = fixtures()[slug + "/" + name];
    if (!data) fail(404, "not_found", "Not found", path);
    return data;
  }

  function keyed(slug, name, key, path) {
    const entry = file(slug, name, path)[key];
    if (!entry) fail(404, "not_found", "Not found", path);
    return entry;
  }

  function me() {
    return fixtures()["me.json"];
  }

  function openFor(slug) {
    return file(slug, "requests.json", "").items.filter((r) => r.status === "open");
  }

  function project(slug, path) {
    return file(slug, "project.json", path);
  }

  // Logo and banner (docs/api.md §11.2). A fixture project points at an
  // image next to its JSON; an upload in this tab becomes an object URL.
  const IMAGE_KINDS = ["logo", "banner"];
  const IMAGE_TYPES = ["image/png", "image/jpeg", "image/webp"];
  const IMAGE_MAX = 1024 * 1024;
  const uploaded = {};  // "<slug>/<kind>" -> object URL
  const forgeImages = {};  // "<slug>/<kind>" -> the forge's image an upload replaced
  let imageSerial = 0;
  let uploadSerial = 0;
  const attachmentBlobs = {};  // "<slug>/<attachment id>" -> object URL of the file uploaded in this tab
  const earlierRepos = {};  // "<slug> <url>" -> the repository and export it had, for a repository set again
  const webhooks = {};  // slug -> the forge webhook's secret and times (§17.4), fixture mode only
  // The address a forge would deliver to: this page's origin, or a placeholder on file://.
  const hubOrigin = () => (window.location && window.location.origin && window.location.origin !== "null" ? window.location.origin : "https://<hub>");
  const avatarChanges = {};  // member id -> times of its last PUT or DELETE (§6.10: 10 per hour)

  function runnersFile() {
    return fixtures()["runners.json"];
  }

  function runnerOf(id, path) {
    const r = runnersFile().items.find((x) => x.id === id);
    if (!r) fail(404, "not_found", "no such runner", path);
    return r;
  }

  let taskSerial = 0;
  let consentSerial = 0;
  // tasks:admin and tasks:review, by the human's trust and role in a project (§2.3).
  const mineIn = (slug) => me().projects.find((p) => p.slug === slug) || {};
  const trustIn = (slug) => mineIn(slug).trust;
  // Trust owner or admin, never a proxy (§2.3, hub/scopes.py).
  const governing = (x) => !!x && ["owner", "admin"].includes(x.trust) && x.role !== "proxy";
  const tasksAdmin = (slug) => governing(mineIn(slug));
  const tasksReview = (slug) => tasksAdmin(slug) || (mineIn(slug).trust !== "guest" && mineIn(slug).role === "reviewer");

  // A card's PATCH as the hub checks it (hub cards.check_transition).
  // Subtasks and related cards (§6.4), checked on the card as it would be
  // after the write: two levels, no closed parent, no release, no cycle with
  // depends_on, and under policy.subtasks "proposed" a child that is not
  // proposed only for tasks:admin. Mutates the card and the counts.
  const CLOSED_TASK = ["done", "cancelled"];
  function childrenOf(list, id) {
    const kids = list.filter((t) => t.parent === id);
    return { open: kids.filter((t) => !CLOSED_TASK.includes(t.status)).length, total: kids.length };
  }
  // tasks:admin for the subtask policy: the signed-in human, or ?as= in
  // fixture mode, so that a member's subtask can be tried end to end.
  const subtaskAdmin = (slug, path) => (fixtureAs ? caller(slug, path).admin : tasksAdmin(slug));
  function subtaskEdges(slug, list, card, body, path, before) {
    const after = Object.assign({}, card, "parent" in body ? { parent: body.parent } : {}, "status" in body ? { status: body.status } : {},
      "depends_on" in body ? { depends_on: body.depends_on } : {});
    if ("parent" in body && body.parent !== null) {
      const p = list.find((t) => t.id === body.parent);
      if (!p) fail(400, "invalid", "the request does not validate", path, { fields: { parent: "unknown_task" } });
      const why = p.id === card.id ? "self" : p.kind === "release" || card.kind === "release" ? "release_card"
        : p.parent ? "too_deep" : list.some((t) => t.parent === card.id) ? "has_children"
        : CLOSED_TASK.includes(p.status) && before.parent !== p.id ? "parent_closed"
        : (after.depends_on || []).includes(p.id) ? "cycle" : null;
      if (why) fail(400, "invalid", "the request does not validate", path, { fields: { parent: why } });
    }
    if ("related" in body) {
      const bad = (body.related || []).find((x) => x === card.id || !list.some((t) => t.id === x));
      if (bad) fail(400, "invalid", "the request does not validate", path, { fields: { related: bad === card.id ? "self" : "unknown_task" } });
    }
    const policy = (project(slug, path).policy || {}).subtasks || "proposed";
    const newlyOpenChild = after.parent && after.status !== "proposed" && !(before.parent && before.status !== "proposed");
    if (policy === "proposed" && newlyOpenChild && !subtaskAdmin(slug, path)) {
      fail(403, "forbidden", "under the project's subtask policy a subtask starts as proposed; an admin opens it", path, { reason: "subtasks_proposed" });
    }
    const oldParent = before.parent;
    if ("parent" in body) card.parent = body.parent;
    if ("related" in body) {
      const was = card.related || [];
      card.related = [...new Set(body.related || [])];
      // related is symmetric: the hub mirrors it on the other card.
      list.forEach((t) => {
        if (t.id === card.id) return;
        const has = card.related.includes(t.id);
        t.related = (t.related || []).filter((x) => x !== card.id).concat(has ? [card.id] : []);
        if (!has && was.includes(t.id)) t.related = t.related.filter((x) => x !== card.id);
      });
    }
    [oldParent, card.parent].filter(Boolean).forEach((pid) => { const p = list.find((t) => t.id === pid); if (p) p.children = childrenOf(list, pid); });
  }

  function invitationsOf(slug) {
    const data = fixtures();
    if (!data[slug + "/invitations.json"]) data[slug + "/invitations.json"] = { items: [] };
    return data[slug + "/invitations.json"].items;
  }

  function patchCard(slug, id, body, path) {
    const list = file(slug, "tasks.json", path).items;
    const card = list.find((x) => x.id === id);
    if (!card) fail(404, "not_found", "no such card", path);
    const meId = me().member.id;
    const holds = !!(card.claim && card.claim.holder === meId);
    const keys = Object.keys(body);
    const reviewMove = keys.length === 1 && keys[0] === "status" && card.status === "review" && ["done", "in_progress"].includes(body.status);
    const authority = project(slug, path).policy.done_authority;
    const hasAuthority = authority === "holder" ? holds : authority === "reviewer" ? tasksReview(slug) : tasksAdmin(slug);
    const editor = holds || card.created_by === meId || tasksAdmin(slug);
    if (!editor && !(reviewMove && hasAuthority)) fail(403, "forbidden", "only the holder, the creator or an admin edits a card", path, { scope: "tasks:admin" });
    if ("parent" in body || "related" in body || ("status" in body && card.parent)) {
      subtaskEdges(slug, list, card, body, path, { parent: card.parent || null, status: card.status });
    }
    if ("status" in body && body.status !== card.status) {
      const from = card.status;
      const to = body.status;
      const closed = ["done", "cancelled"];
      if (to === "cancelled" && !closed.includes(from)) {
        if (!(tasksAdmin(slug) || (from === "open" && card.created_by === meId))) fail(403, "forbidden", "cancelling this card needs tasks:admin", path, { scope: "tasks:admin" });
      } else if ((from === "proposed" && to === "open") || (from === "open" && to === "proposed")) {
        // the simple ones
      } else if (from === "review" && (to === "done" || to === "in_progress")) {
        if (!hasAuthority) fail(403, "forbidden", "this needs done authority", path, { scope: "tasks:review" });
      } else if (!(from === "in_progress" && to === "done" && authority === "holder" && holds)) {
        fail(409, "invalid_transition", "not a transition the hub allows", path, { from, to });
      }
      if (to === "done") {
        const open = (card.depends_on || []).filter((d) => { const o = list.find((t) => t.id === d); return o && !closed.includes(o.status); });
        // A parent waits for its children (§6.4).
        const kids = list.filter((t) => t.parent === card.id && !closed.includes(t.status)).map((t) => t.id);
        if (open.length || kids.length) fail(409, "dependencies_open", "dependencies or children are not done", path, Object.assign({ open: open.concat(kids) }, kids.length ? { children: kids } : {}));
        // A release is done only when the hub judges it ready (§6.7).
        if (card.kind === "release" && !(card.release && card.release.readiness && card.release.readiness.ready)) {
          fail(409, "release_not_ready", "the release is not ready", path, { blocking: (card.release.readiness || {}).blocking || [] });
        }
      }
      card.status = to;
      card.closed_at = closed.includes(to) ? nowIso() : null;
      // A closed card holds no claim.
      if (closed.includes(to)) card.claim = null;
    }
    // A child's closing changes its parent's counts.
    if (card.parent) { const p = list.find((t) => t.id === card.parent); if (p) p.children = childrenOf(list, p.id); }
    ["title", "body", "label", "area"].forEach((f) => { if (f in body) card[f] = body[f]; });
    // §6.8: a contract card's file and section, checked as the hub checks them.
    if (body.contract) {
      if (card.kind !== "contract") fail(400, "invalid", "contracts only", path, { fields: { contract: "contracts_only" } });
      const c = body.contract;
      if ("path" in c && (!c.path || /^\/|:|\\|(^|\/)\.{0,2}(\/|$)/.test(c.path))) fail(400, "invalid", "not a repository path", path, { fields: { "contract.path": "not_a_path" } });
      if (c.section != null && !/^[^\s#]+$/.test(c.section)) fail(400, "invalid", "not a heading number", path, { fields: { "contract.section": "invalid" } });
      card.contract = Object.assign({}, card.contract, "path" in c ? { path: c.path } : {}, "section" in c ? { section: c.section } : {});
    }
    card.updated_at = nowIso();
    return card;
  }

  let attachSerial = 0;
  const activeAttachments = (slug) => runnersFile().attachments
    .filter((a) => a.project === fullOf(slug) && !a.detached_at)
    .sort((x, y) => runnerOf(x.runner_id, "").name.localeCompare(runnerOf(y.runner_id, "").name));
  function attachmentView(a) {
    const counts = (runnersFile().active_placements || {})[a.runner_id] || {};
    return { id: a.id, runner: runnerOf(a.runner_id, ""), project: a.project, attached_by: a.attached_by,
      attached_at: a.attached_at, detached_at: a.detached_at, active_placements: a.detached_at ? 0 : counts[a.project] || 0 };
  }

  // A release card that may still change: closed ones are a record.
  function releaseCard(slug, id, path) {
    const card = file(slug, "tasks.json", path).items.find((x) => x.id === id);
    if (!card) fail(404, "not_found", "no such card", path);
    if (card.kind !== "release") fail(400, "invalid", "releases only", path, { fields: { release: "releases_only" } });
    if (card.status === "done" || card.status === "cancelled") {
      fail(409, "invalid_transition", "a closed release does not change", path, { from: card.status, to: card.status });
    }
    return card;
  }

  // members:admin in a project: a human owner or admin there (§2.3).
  const membersAdmin = (slug) => {
    const mine = me().projects.find((p) => p.slug === slug);
    return governing(mine);
  };
  // Who changes a membership: the signed-in human, or ?as= in fixture mode.
  function caller(slug, path) {
    if (!fixtureAs) return { member: me().member, admin: membersAdmin(slug) };
    const x = member(slug, fixtureAs, path);
    return { member: x, admin: governing(x) };
  }
  // §2.3 ᵃ: an admin agent changes only other agents' memberships with trust
  // member or guest, to those trusts and the work roles; capabilities, admin,
  // owner, proxy and manager stay a human's.
  const AGENT_TRUSTS = ["member", "guest"];
  const AGENT_ROLES = ["coder", "reviewer", "tester", "designer", "writer", "ops"];
  function agentLimits(who, target, body, path) {
    const human = () => fail(403, "forbidden", "a human's change", path, { scope: "members:admin", reason: "humans_only" });
    if (who.kind !== "agent") return;
    if (target.kind !== "agent" || target.id === who.id || !AGENT_TRUSTS.includes(target.trust) || target.role === "proxy") human();
    if (body && ("capabilities" in body || ("trust" in body && !AGENT_TRUSTS.includes(body.trust))
      || ("role" in body && !AGENT_ROLES.includes(body.role)))) human();
  }
  // Changing the role of or pausing a reviewer or the contract arbiter, and
  // any removal, by an agent waits for a human's go: 202 with the request.
  function consentFor(who, title) {
    if (who.kind !== "agent") return null;
    return { id: "req-c" + String(++consentSerial).padStart(3, "0"), class: "consent", status: "open", to: "owner", title, created_at: nowIso() };
  }
  const guarded = (slug, target) => ["reviewer", "tester"].includes(target.role)
    || [].concat((project(slug, "").policy || {}).contract_arbiter || []).some((a) => a === target.id || a === target.handle);
  // A member's avatar as §6.10 keeps it: one per account or profile, so
  // every object that names the member carries the same avatar_url.
  function setAvatar(id, url, source) {
    const all = fixtures();
    const objects = [all["me.json"].member].concat((all["agents.json"] || { items: [] }).items,
      ...Object.keys(all).filter((k) => k.endsWith("/members.json")).map((k) => all[k].items));
    objects.filter((x) => x && x.id === id).forEach((x) => { x.avatar_url = url; x.avatar_source = source; });
    // An organisation's view carries the picture alone: it has no forge source (§6.26).
    ((all["orgs.json"] || { items: [] }).items).filter((o) => o.id === id).forEach((o) => { o.avatar_url = url; });
    return { avatar_url: url, avatar_source: source };
  }
  function avatarRoute(idOf) {
    return (m, body, path) => {
      const id = idOf(m, path);
      const now = Date.now();
      const recent = (avatarChanges[id] || []).filter((t) => now - t < 3600000);
      if (recent.length >= 10) fail(429, "rate_limited", "at most 10 changes of one avatar per hour", path);
      if (body && body.blob) {
        if (!IMAGE_TYPES.includes(body.type)) fail(400, "invalid", "not PNG, JPEG or WebP", path, { fields: { body: "unsupported_type" } });
        if (body.size > IMAGE_MAX) fail(400, "invalid", "larger than 1 MiB", path, { fields: { body: "too_large" } });
      }
      avatarChanges[id] = recent.concat(now);
      const key = "avatar/" + id;
      if (uploaded[key] && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(uploaded[key]);
      delete uploaded[key];
      if (!body || !body.blob) return setAvatar(id, null, null);
      uploaded[key] = window.URL && URL.createObjectURL ? URL.createObjectURL(body.blob) : "uploaded-" + key;
      return setAvatar(id, uploaded[key], "uploaded");
    };
  }
  // /agents/{id}/avatar: the profile's owner only; any other is not_found.
  // §6.26 Organisations in fixture mode (fixtures/orgs.json).
  // The hub's reserved handles: DASHBOARD_WORDS in hub/src/maity_hub/namespace.py
  // (docs/api.md §6.25 "Dashboard routes and handles", §16.11 with #601);
  // change this list with it.
  const ORG_RESERVED = ["account", "admin", "agents", "all", "chats", "components", "invite", "join", "login", "new", "notifications",
    "observe", "p", "register", "requests", "runners", "s", "settings", "sign-in"];
  let orgInviteSerial = 0;
  const orgsData = () => {
    const all = fixtures();
    all["orgs.json"] = all["orgs.json"] || { items: [], members: {}, invitations: {} };
    return all["orgs.json"];
  };
  const humanOnly = (path) => { if (me().member.kind !== "human") fail(403, "forbidden", "humans only", path, { reason: "humans_only" }); };
  const orgRole = (org) => ((orgsData().members[org.id] || []).find((x) => x.id === me().member.id) || {}).role || null;
  const orgView = (org) => Object.assign({}, org, { my_role: orgRole(org) });
  // A member's organisation by its handle or an alias; not_found for anyone else.
  function orgOf(handle, path) {
    humanOnly(path);
    const org = orgsData().items.find((o) => o.handle === handle || (o.aliases || []).includes(handle));
    if (!org || !orgRole(org)) fail(404, "not_found", "Not found", path);
    return org;
  }
  function orgNeeds(org, roles, path) {
    if (!roles.includes(orgRole(org))) fail(403, "forbidden", "not for your role", path, { reason: "org_role" });
  }
  // The picture's routes: an owner's, the organisation's id for avatarRoute.
  function ownerOrg(m, path) {
    const org = orgOf(m[1], path);
    orgNeeds(org, ["owner"], path);
    return org.id;
  }
  const ownAgent = (m, path) => {
    const agent = (fixtures()["agents.json"] || { items: [] }).items.find((a) => a.id === m[1]);
    if (!agent || agent.owner_id !== me().member.id) fail(404, "not_found", "Not found", path);
    return agent.id;
  };
  function eventsOf(slug) {
    const all = fixtures();
    if (!all[slug + "/events.json"]) all[slug + "/events.json"] = { items: [] };
    return all[slug + "/events.json"].items;
  }
  const nextLogSeq = (log) => Math.max(9000, ...log.map((e) => e.seq)) + 1;
  // §17 in fixture mode: fixtures/<slug>/ticker.json, the items as events and
  // the reader's subscription; a project without the file has an empty one.
  function tickerOf(slug) {
    const all = fixtures();
    if (!all[slug + "/ticker.json"]) all[slug + "/ticker.json"] = { subscription: { follow: { areas: [], types: [] }, mute: { areas: [], types: [] }, updated_at: null }, items: [] };
    return all[slug + "/ticker.json"];
  }
  const personalRequests = () => (fixtures()["personal-requests.json"] || { items: [] }).items;
  const prefs = () => fixtures()["preferences.json"];
  function utf8Bytes(text) {
    let n = 0;
    for (const ch of text) { const c = ch.codePointAt(0); n += c < 0x80 ? 1 : c < 0x800 ? 2 : c < 0x10000 ? 3 : 4; }
    return n;
  }
  // The next version of the preferences, as the hub writes it (§19.4).
  function writePrefs(text, by, proposedBy, confirmedBy) {
    const at = nowIso();
    const next = { human_id: me().member.id, markdown: text, version: prefs().current.version + 1,
      by, proposed_by: proposedBy, confirmed_by: confirmedBy, updated_at: at };
    prefs().current = next;
    prefs().versions.unshift({ markdown: text, version: next.version, by, proposed_by: proposedBy, confirmed_by: confirmedBy, at });
    return next;
  }
  // A personal request as GET /requests/{id} shows it: a preference proposal
  // with the human's current text and whether its base is stale.
  function personalView(req) {
    const p = req.memory_proposal;
    if (!p || p.store !== "preferences" || req.status !== "open") return req;
    const now = prefs().current;
    return Object.assign({}, req, { memory_proposal: Object.assign({}, p, {
      current: { markdown: now.markdown, version: now.version }, stale: p.base_version !== now.version }) });
  }
  // A decision only to who may read its request (§17.5): here, its audience.
  const tickerReadable = (e) => e.payload.type !== "decision" || (e.audience || []).includes("member:" + me().member.id);
  // detail is added at read time from the request (§17.5): its title and
  // the chosen reply's label, null for an answer in words.
  function tickerDetail(slug, p) {
    if (p.type !== "decision" || !p.request) return null;
    const req = ((fixtures()[slug + "/requests.json"] || {}).items || []).find((r) => r.id === p.request.id);
    if (!req) return null;
    const reply = req.answer && req.answer.reply_id ? (req.replies || []).find((r) => r.id === req.answer.reply_id) : null;
    return { request_title: req.title, reply_label: reply ? reply.label : null };
  }
  // The listing's compact form (§17.9), with the reader's own why and muted.
  function tickerItem(slug, e) {
    const p = e.payload;
    const mine = (p.reasons || []).find((r) => r.member_id === me().member.id);
    return { id: "tck-" + e.seq, seq: e.seq, at: e.at, type: p.type, text: p.text, url: p.url, actor: e.actor, subject: e.subject,
      areas: p.areas || [], contract: p.contract, tasks: p.tasks || [], for_me: !!mine, why: mine ? mine.why : [], muted: mine ? mine.muted : false,
      detail: tickerDetail(slug, p), redacted: !!e.redacted, _paths: p.paths || [] };
  }
  // The member owning the narrowest area that contains a path (§6.2), or null.
  function areaOwner(members, path) {
    const owning = members.filter((mm) => (mm.areas || []).some((a) => a === "/" || path === a || path.startsWith(a.endsWith("/") ? a : a + "/")));
    const depth = (mm) => Math.max(...mm.areas.filter((a) => a === "/" || path === a || path.startsWith(a.endsWith("/") ? a : a + "/")).map((a) => (a === "/" ? 0 : a.length)));
    return owning.sort((a, b) => depth(b) - depth(a))[0] || null;
  }

  // §8.2's readable set: the audience by all, member or role, one's own
  // events; owners and admins every event but a conversation's, which only
  // its audience reads. "_conversation" is the fixture's note of what the
  // hub stores and the event no longer shows once redacted; never served.
  function readable(slug, e) {
    const meId = me().member.id;
    const mine = mineIn(slug);
    if (e.actor && e.actor.member_id === meId) return true;
    const named = (e.audience || []).some((t) => t === "all" || t === "member:" + meId || t === "role:" + mine.role || t === "trust:" + mine.trust);
    if (e._conversation) return (e.audience || []).includes("member:" + meId);
    return named || ["owner", "admin"].includes(mine.trust);
  }
  const served = (e) => JSON.parse(JSON.stringify(e, (k, v) => (k.startsWith("_") ? undefined : v)));
  // §8.7 in fixture mode: fixtures/<slug>/attachments.json, made on first use.
  // ?attachments=off is an instance without a store: every attachment call
  // and a message that names one get 409 attachments_not_configured.
  const ATTACHMENT_MAX = 10 * 1024 * 1024;
  function attachmentsOn(path) {
    if (new URLSearchParams(window.location.search).get("attachments") === "off") {
      fail(409, "attachments_not_configured", "attachments are not set up on this instance", path);
    }
  }
  function attachmentsOf(slug) {
    const all = fixtures();
    if (!all[slug + "/attachments.json"]) all[slug + "/attachments.json"] = { items: [] };
    return all[slug + "/attachments.json"].items;
  }
  function attachmentOf(slug, id, path) {
    const a = attachmentsOf(slug).find((x) => x.id === id);
    if (!a) fail(404, "not_found", "Not found", path);
    return a;
  }
  // Another member's pending upload: its size and uploader, nothing that says what it is.
  const hiddenUpload = (a) => ({ id: a.id, uploaded_by: a.uploaded_by, size: a.size, uploaded_at: a.uploaded_at, expires_at: a.expires_at,
    name: null, type: null, kind: null, sha256: null, width: null, height: null, message_seq: null });
  // The ids a message names, each a pending upload of the poster; bound to it.
  function bindAttachments(slug, ids, seq, path) {
    if (!ids || !ids.length) return [];
    attachmentsOn(path);
    if (ids.length > 10) fail(400, "invalid", "at most 10 attachments", path, { fields: { attachments: "too_many" } });
    if (["accepted", "archived"].includes(project(slug, path).state)) fail(409, "project_closed", "the project is closed", path);
    const list = attachmentsOf(slug);
    const bad = {};
    ids.forEach((id) => {
      const a = list.find((x) => x.id === id && x.uploaded_by === me().member.id && !x.deleted_at);
      if (!a) bad[id] = "unknown";
      else if (a.message_seq !== null) bad[id] = "already_attached";
    });
    if (Object.keys(bad).length) fail(400, "invalid", "attachments", path, { fields: { attachments: bad } });
    return ids.map((id) => {
      const a = list.find((x) => x.id === id);
      a.message_seq = seq;
      return { id: a.id, name: a.name, size: a.size, type: a.type, kind: a.kind, width: a.width, height: a.height };
    });
  }
  function messageOfSeq(slug, seq) {
    const g = Object.values(groupChats(slug)).find((c) => c.items.some((x) => x.seq === seq));
    if (g) return { group: g };
    const d = Object.entries(fixtures()[slug + "/conversations.json"] || {}).find(([, c]) => c.items.some((x) => x.seq === seq));
    return d ? { direct: d[0] } : null;
  }
  // A message item as §9 shows it (#206): redacted and redaction always there.
  const messageView = (x) => Object.assign({ redacted: false, redaction: null }, x);
  // §9.2 group chats in fixture mode: fixtures/<slug>/group-chats.json,
  // each { view, items, read }; joined_seq is where a participant's window begins.
  function groupChats(slug) {
    const all = fixtures();
    if (!all[slug + "/group-chats.json"]) all[slug + "/group-chats.json"] = {};
    return all[slug + "/group-chats.json"];
  }
  function groupChat(slug, id, path) {
    const c = groupChats(slug)[id];
    if (!c) fail(404, "not_found", "Not found", path);
    return c;
  }
  const participantOf = (m, at, seq) => ({ member_id: m.id, kind: m.kind, handle: m.handle, owner_id: m.kind === "agent" ? m.owner_id : null, joined_at: at, joined_seq: seq });
  function windowOf(c, memberId) {
    const p = c.view.participants.find((x) => x.member_id === memberId);
    return c.items.filter((x) => x.seq > (p ? p.joined_seq : 0));
  }
  // §9.3 for one project (m[1]: its fixture key), shared by the project's
  // route and the list across projects.
  function conversationList(m, path, query) {
    const all = file(m[1], "conversations.json", path);
    const members = file(m[1], "members.json", path).items;
    const preview = (last) => last && { seq: last.seq, from: last.from, body: last.redacted ? null : [...last.body].slice(0, 200).join(""),
      sent_at: last.sent_at, redacted: !!last.redacted };
    // §9.2: an owner outside the project sees only the chats its agents are
    // in, and only with observed=true; no direct chat, nothing else.
    const outside = !me().projects.some((p) => p.slug === m[1]);
    // Neither a member nor an agent there: the route does not say the project exists (§9.2).
    if (outside && !(fixtures()["agents.json"] || { items: [] }).items.some((a) => a.owner_id === me().member.id
      && (a.memberships || []).some((x) => x.project === fullOf(m[1])))) fail(404, "not_found", "Not found", path);
    const direct = outside ? [] : Object.keys(all).map((agentId) => {
      const items = all[agentId].items;
      const last = items.length ? items[items.length - 1] : null;
      const agent = members.find((x) => x.id === agentId);
      return {
        id: agentId, kind: "direct", agent_id: agentId, title: null, access: "party", closed_at: null,
        participants: [{ member_id: me().member.id, kind: "human", handle: me().member.handle },
          { member_id: agentId, kind: "agent", handle: agent ? agent.handle : agentId }],
        last_message_at: last ? last.sent_at : null,
        unread: items.filter((x) => x.from === agentId && !x.seen_by_human).length,
        mentions_unread: 0,
        // §9: the newest message as a preview, its body cut at 200 code points.
        last_message: preview(last),
      };
    });
    const groups = Object.values(groupChats(m[1])).map((g) => groupItem(m[1], g, path)).filter(Boolean)
      .filter((g) => g.access === "participant" || query.get("observed") === "true")
      .map((g) => {
        const c = groupChats(m[1])[g.id];
        const win = windowOf(c, me().member.id);
        const last = win.length ? win[win.length - 1] : null;
        const readTo = c.read[me().member.id] || 0;
        const theirs = win.filter((x) => x.from !== me().member.id && x.seq > readTo);
        return Object.assign({}, g, {
          participants: g.participants.map((x) => ({ member_id: x.member_id, kind: x.kind, handle: x.handle })),
          last_message_at: last ? last.sent_at : null, last_message: preview(last),
          unread: g.access === "observer" ? null : theirs.length,
          mentions_unread: g.access === "observer" ? null : theirs.filter((x) => (x.mentions || []).some((mm) => mm.member_id === me().member.id)).length,
        });
      });
    const at = (c) => c.last_message_at || c.created_at || "";
    return { items: direct.concat(groups).sort((a, b) => (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : 0)), next_cursor: null };
  }

  // The view as the caller may see it, or null when it may not.
  function groupItem(slug, c, path) {
    const meId = me().member.id;
    const v = c.view;
    const participant = v.participants.some((x) => x.member_id === meId);
    const observers = [...new Set(v.participants.filter((x) => x.kind === "agent" && x.owner_id && !v.participants.some((y) => y.member_id === x.owner_id)).map((x) => x.owner_id))];
    if (!participant && !observers.includes(meId)) return null;
    return { id: v.id, kind: "group", title: v.title, created_by: v.created_by, created_at: v.created_at,
      participants: v.participants.map((x) => ({ member_id: x.member_id, kind: x.kind, handle: x.handle, owner_id: x.owner_id, joined_at: x.joined_at })),
      observers, closed_at: v.closed_at, closed_reason: v.closed_reason, access: participant ? "participant" : "observer" };
  }
  // The creator while a participant, or a human participant with members:admin; else refused.
  function managed(slug, id, path) {
    const c = groupChat(slug, id, path);
    const item = groupItem(slug, c, path);
    if (!item) fail(404, "not_found", "Not found", path);
    if (item.access === "observer") fail(403, "forbidden", "an observer does not manage", path, { reason: "observer" });
    if (c.view.closed_at) fail(409, "conversation_closed", "the chat is closed", path);
    if (c.view.created_by !== me().member.id && !["owner", "admin"].includes(trustIn(slug))) fail(403, "forbidden", "members:admin or the creator", path, { scope: "members:admin" });
    return c;
  }
  // §18.2 counts, overall and per project. Items from events carry seq,
  // those from account records record "acr-<n>"; a position is "a.b".
  // §18.1 since 2026-10-26: only what the human must react to.
  const KINDS = ["inbox", "chat", "mention", "security"];
  function notificationCounts() {
    const counts = {};
    KINDS.forEach((k) => { counts[k] = 0; });
    const byProject = {};
    const of = (slug) => byProject[slug] || (byProject[slug] = Object.assign({ member: true }, ...KINDS.filter((k) => k !== "security").map((k) => ({ [k]: 0 }))));
    me().projects.forEach((p) => { const n = openFor(p.slug).length; counts.inbox += n; if (n) of(p.full_name).inbox += n; });
    fixtures()["notifications.json"].items.forEach((x) => {
      // A pending registration or a disabled address counts until the matter
      // is closed, read or not (§18.2).
      if (x.kind === "inbox" && x.open_matter) { counts.inbox += 1; return; }
      if (x.read) return;
      // A personal request of a project one is no member of (§7): counted
      // in inbox, on an entry with member false; the rest come from /me.
      if (x.kind === "inbox") {
        if (x.project && x.project.member === false) { counts.inbox += 1; of(x.project.full_name).inbox += 1; of(x.project.full_name).member = false; }
        return;
      }
      counts[x.kind] += 1;
      if (x.project && x.kind !== "security") of(x.project.full_name)[x.kind] += 1;
    });
    counts.total = counts.inbox + counts.chat + counts.mention;
    Object.values(byProject).forEach((c) => { c.total = c.inbox + c.chat + c.mention; });
    return { counts, by_project: byProject };
  }
  // §2.6.5 in fixture mode: fixtures/sessions.json, its "current" the session of this tab.
  const activeSessions = () => fixtures()["sessions.json"].items.filter((s) => !s.ended_at);
  const currentSession = () => fixtures()["sessions.json"].items.find((s) => s.id === fixtures()["sessions.json"].current);
  const youngerThanHour = (s) => Date.now() - Date.parse(s.created_at) < 3600 * 1000;
  function sessionOf(id, path) {
    const s = fixtures()["sessions.json"].items.find((x) => x.id === id);
    if (!s) fail(404, "not_found", "Not found", path);
    return s;
  }
  // Who may end which (§2.6.5): good standing ends any; otherwise never one
  // in good standing, and while under an hour old no older one; itself always.
  function mayEnd(s, path) {
    const cur = currentSession();
    if (s.id === cur.id || cur.good_standing) return;
    if (s.good_standing) fail(403, "forbidden", "not in good standing", path, { reason: "not_in_good_standing" });
    if (youngerThanHour(cur) && Date.parse(s.created_at) < Date.parse(cur.created_at)) fail(403, "forbidden", "this session is too new", path, { reason: "session_too_new" });
  }
  // Ending one ends the sessions it approved by device code, and theirs.
  function endSession(s, by) {
    Object.assign(s, { ended_at: nowIso(), ended_by: by });
    activeSessions().filter((x) => x.approved_by === s.id).forEach((x) => endSession(x, by));
  }
  // A security item is marked read only from a session in good standing that
  // existed before what it reports, never from the reported session (§18.3).
  function mayMarkSecurity(x) {
    const cur = currentSession();
    if (!cur || !cur.good_standing) return false;
    if (x.target && x.target.type === "session") {
      const reported = fixtures()["sessions.json"].items.find((s) => s.id === x.target.id);
      return !!reported && reported.id !== cur.id && Date.parse(cur.created_at) < Date.parse(reported.created_at);
    }
    return Date.parse(cur.created_at) < Date.parse(x.at);
  }

  // A position's two parts, and whether an item lies past one (§18.2).
  const parts = (pos) => String(pos).split(".").map(Number);
  const recordNo = (x) => (x.record ? Number(x.record.slice(4)) : null);
  const pastOf = (x, pos) => { const [a, b] = parts(pos); return x.record ? recordNo(x) > b : x.seq > a; };
  const headOf = (items) => Math.max(0, ...items.filter((x) => !x.record).map((x) => x.seq)) + "."
    + Math.max(0, ...items.filter((x) => x.record).map(recordNo));
  // One order: by at, events before records (§18.2).
  const inOrder = (a, b) => (a.at < b.at ? -1 : a.at > b.at ? 1 : (a.record ? 1 : 0) - (b.record ? 1 : 0));
  // An agent's owner as §6.2 shows it: always the human, member or not.
  function humanOf(id) {
    const m = me().member;
    if (id === m.id) return { id: m.id, handle: m.handle, display_name: m.display_name };
    return { id, handle: id, display_name: id };
  }

  function member(slug, id, path) {
    const m = file(slug, "members.json", path).items.find((x) => x.id === id);
    if (!m) fail(404, "not_found", "Not found", path);
    return m;
  }

  // The status filter of a list: the default, a comma list, or all.
  function statusFilter(query, fallback) {
    const value = query.get("status") || fallback;
    if (value === "all") return () => true;
    const wanted = value.split(",");
    return (item) => wanted.includes(item.status);
  }

  const SLUG = /^[a-z0-9][a-z0-9-]{1,62}$/;

  // The policy fields each preset fills (docs/api.md §6.1); a missing
  // contract_arbiter is the owner.
  // §6.21: the setup options in their cards' order, with the titles the hub
  // gives the cards, verbatim.
  const SETUP_CARDS = [
    ["keep_the_why_init", "Set up Keep the Why in the repository"],
    ["keep_the_why_badge", "Add the Keep the Why badge to the README"],
    ["maity_badge", "Add the Maity badge to the README"],
  ];
  // One open setup card per chosen option, made when the project has a
  // repository (routes/projects.py, project_setup.make_cards).
  function makeSetupCards(slug, setup, by, url) {
    const list = fixtures()[slug + "/tasks.json"];
    setup.cards = SETUP_CARDS.filter(([key]) => setup[key]).map(([key, title]) => {
      const id = localId("tsk");
      list.items.push({
        id, kind: "setup", title, body: "In " + url + ": " + title.toLowerCase() + ", as a pull request against its default branch.",
        label: "chore", status: "open", area: "/", created_by: by, assigned_to: null, claim: null, checkpoint: null,
        depends_on: [], ships_with: [], blocked_by_request: null, ktw_ref: null, report: null, release: null, contract: null,
        created_at: nowIso(), updated_at: nowIso(), closed_at: null,
      });
      return id;
    });
  }

  const PRESETS = {
    hierarchical: {
      claim_policy: "self-claim", done_authority: "reviewer", contract_arbiter: "trust:admin",
      tag_authority: "human", steward_writes: "cards_only", lease_seconds: 7200,
    },
    solo: {
      claim_policy: "self-claim", done_authority: "holder", contract_arbiter: null,
      tag_authority: "human", steward_writes: "cards_only", lease_seconds: 7200,
    },
  };

  // docs/api.md §3, §6.2: a briefing is Markdown of at most 16 KiB,
  // counted in characters (code points) as the hub counts them.
  const BRIEFING_CHARS = 16 * 1024;

  // [method, pattern, handler(match, body, path, query)]. One row per
  // endpoint the views use; the patterns match the path below /api/v1
  // without the query string.
  const routes = [
    // §2.6.1–2.6.3 in one tab: this tab makes the code, and a simulated
    // phone has entered it by the second read, so the approval can be seen.
    ["GET", /^\/auth\/methods$/, () => ({ password: true, device_code: true, email_link: true, registration: false, terms: null })],
    // §3.4: the invitation page and accepting, signed out and in; per token
    // fixtures/invitations.json says what the page shows or how accept refuses.
    ["GET", /^\/invitations\/([^/]+)$/, (m, body, path) => {
      const view = (fixtures()["invitations.json"].pages || {})[m[1]];
      if (!view) fail(404, "not_found", "Not found", path);
      return view;
    }],
    ["POST", /^\/invitations\/([^/]+)\/accept$/, (m, body, path) => {
      if (!fixtureSignedIn) fail(401, "unauthenticated", "Not signed in", path);
      const data = fixtures()["invitations.json"];
      const view = (data.pages || {})[m[1]];
      if (!view) fail(404, "not_found", "Not found", path);
      const no = (data.refusals || {})[m[1]];
      if (no) fail(no.status, no.code, no.message, path, no.details || {});
      delete data.pages[m[1]];
      return { id: me().member.id, kind: "human", handle: me().member.handle, display_name: me().member.display_name, trust: view.trust, role: view.role };
    }],
    // §3.4: a project's invitations, for a human with members:admin.
    ["GET", /^\/projects\/([^/]+)\/invitations$/, (m, body, path) => {
      if (!["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "members:admin", path, { scope: "members:admin" });
      return { items: invitationsOf(m[1]).slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1)).map((x) => Object.assign({}, x, { url: undefined })), next_cursor: null };
    }],
    ["POST", /^\/projects\/([^/]+)\/invitations$/, (m, body, path) => {
      const trust = trustIn(m[1]);
      if (!["owner", "admin"].includes(trust)) fail(403, "forbidden", "members:admin", path, { scope: "members:admin" });
      const fields = {};
      // §3.4: trust and role, proxy only with trust admin; owner, admin and proxy only from an owner.
      const wantTrust = body.trust || "member";
      const want = body.role || "coder";
      if (!["owner", "admin", "member", "guest"].includes(wantTrust)) fields.trust = "unknown";
      if (!["coder", "reviewer", "tester", "designer", "writer", "ops", "manager", "proxy"].includes(want)) fields.role = "unknown";
      else if (want === "proxy" && wantTrust !== "admin") fields.role = "proxy_needs_admin";
      if ((["admin", "owner"].includes(wantTrust) || want === "proxy") && trust !== "owner") {
        fail(403, "forbidden", "only an owner invites an owner, an admin or a proxy", path, { reason: "owner_only" });
      }
      const ttl = body.ttl_seconds === undefined ? 86400 : body.ttl_seconds;
      if (!(ttl >= 60 && ttl <= 604800)) fields.ttl_seconds = "out_of_range";
      if (body.address !== undefined && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(body.address))) fields.address = "invalid";
      if (body.note !== undefined && utf8Bytes(String(body.note)) > 1024) fields.note = "too_long";
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      const list = invitationsOf(m[1]);
      const token = "fx" + String(list.length + 1).padStart(20, "0");
      const at = nowIso();
      const made = { id: "inv-f" + String(list.length + 1).padStart(3, "0"), project: fullOf(m[1]), trust: wantTrust, role: want, address: body.address || null, note: body.note || null,
        created_by: me().member.id, created_at: at, expires_at: new Date(Date.now() + ttl * 1000).toISOString().replace(/\.\d{3}Z$/, "Z"),
        used_at: null, used_by: null, revoked_at: null, voided_at: null };
      list.push(made);
      return Object.assign({}, made, { url: window.location.origin + window.location.pathname + "#/invite/" + token });
    }],
    ["DELETE", /^\/projects\/([^/]+)\/invitations\/([^/]+)$/, (m, body, path) => {
      if (!["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "members:admin", path, { scope: "members:admin" });
      const x = invitationsOf(m[1]).find((i) => i.id === m[2]);
      if (!x) fail(404, "not_found", "Not found", path);
      if (x.revoked_at) return x;
      if (x.used_at || Date.parse(x.expires_at) <= Date.now()) fail(409, "invalid_transition", "not open", path, { to: "revoked", from: x.used_at ? "used" : "expired" });
      x.revoked_at = nowIso();
      return x;
    }],
    ["POST", /^\/auth\/device-codes$/, (m, body, path) => {
      if (!fixtureSignedIn) fail(401, "unauthenticated", "Not signed in", path);
      const code = "K7QM4XPR9D2F";
      deviceSim = { id: "dvc-" + (++deviceSerial), code, status: "waiting", reads: 0, match: 47,
        expires_at: new Date(Date.now() + 5 * 60 * 1000).toISOString().replace(/\.\d{3}Z$/, "Z") };
      return { id: deviceSim.id, code: "K7QM-4XPR-9D2F", url: window.location.origin + window.location.pathname + "#/sign-in/code?c=" + code, expires_at: deviceSim.expires_at };
    }],
    ["GET", /^\/auth\/device-codes\/([^/]+)$/, (m, body, path) => {
      const d = deviceOf(m[1], path);
      if (d.status === "waiting" && ++d.reads >= 2) {
        d.status = "redeemed";
        d.device = { ip: "203.0.113.24", redeemed_at: nowIso(), user_agent: "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 Safari/604.1",
          browser: "Safari", os: "iOS", new_device: true };
      }
      return deviceView(d);
    }],
    ["POST", /^\/auth\/device-codes\/([^/]+)\/approve$/, (m, body, path) => {
      const d = deviceOf(m[1], path);
      if (d.status !== "redeemed") fail(409, "conflict", "the code is not waiting for an approval", path);
      if (body.number !== d.match) { d.status = "denied"; fail(400, "code_invalid", "the code does not work", path); }
      d.status = "approved";
      return deviceView(d);
    }],
    ["POST", /^\/auth\/device-codes\/([^/]+)\/deny$/, (m, body, path) => { const d = deviceOf(m[1], path); d.status = "denied"; return deviceView(d); }],
    ["DELETE", /^\/auth\/device-codes\/([^/]+)$/, (m, body, path) => { const d = deviceOf(m[1], path); d.status = "denied"; return deviceView(d); }],
    // The new device's side: a code typed in, the wait, and the session.
    ["POST", /^\/auth\/device-login$/, (m, body, path) => {
      const typed = String(body.code || "").toUpperCase().replace(/[\s-]/g, "");
      if (!deviceSim || typed !== deviceSim.code || !["waiting", "redeemed"].includes(deviceSim.status) || deviceSim.pending) fail(400, "code_invalid", "the code does not work", path);
      deviceSim.pending = true;
      deviceSim.status = "redeemed";
      return { status: "redeemed", expires_at: deviceSim.expires_at, match_number: deviceSim.match };
    }],
    ["GET", /^\/auth\/device-login$/, (m, body, path) => {
      if (!deviceSim || !deviceSim.pending) fail(404, "not_found", "Not found", path);
      const view = { status: deviceSim.status, expires_at: deviceSim.expires_at, match_number: deviceSim.match };
      if (deviceSim.status === "approved") view.account = { handle: me().member.handle, display_name: me().member.display_name, avatar_url: me().member.avatar_url || null };
      return view;
    }],
    ["POST", /^\/auth\/device-login\/complete$/, (m, body, path) => {
      if (!deviceSim || !deviceSim.pending) fail(404, "not_found", "Not found", path);
      if (deviceSim.status !== "approved") fail(409, "conflict", "the code is not approved", path);
      deviceSim.status = "used";
      fixtureSignedIn = true;
      return { member: me().member, next: "/" };
    }],
    // §2.6.3: always 202; the fixtures' mailed code is 482913.
    ["POST", /^\/auth\/email-link$/, (m, body) => { mailPending = true; mailNext = body.next || "/"; return { expires_in: 900 }; }],
    ["POST", /^\/auth\/email-code$/, (m, body, path) => {
      if (!mailPending || String(body.code || "").replace(/\s/g, "") !== "482913") fail(400, "code_invalid", "the code does not match", path);
      mailPending = false;
      fixtureSignedIn = true;
      return { member: me().member, next: mailNext };
    }],
    ["GET", /^\/auth\/session$/, (m, body, path) => {
      if (!fixtureSignedIn) fail(401, "unauthenticated", "Not signed in", path);
      return Object.assign({ session_id: fixtures()["sessions.json"].current }, fixtures()["auth-session.json"]);
    }],
    // §2.6.5: the human's sessions, newest first; ended ones of 30 days on ask.
    ["GET", /^\/auth\/sessions$/, (m, body, path, query) => {
      const all = fixtures()["sessions.json"];
      const items = all.items.filter((s) => query.get("ended") === "true" || !s.ended_at)
        .slice().sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
        .map((s) => Object.assign({ current: s.id === all.current }, s));
      return { items, next_cursor: null };
    }],
    ["DELETE", /^\/auth\/sessions\/([^/]+)$/, (m, body, path) => {
      const s = sessionOf(m[1], path);
      if (s.ended_at) return { ended: true };
      mayEnd(s, path);
      endSession(s, s.id === fixtures()["sessions.json"].current ? "logout" : "revoked");
      return { ended: true };
    }],
    ["POST", /^\/auth\/sessions\/end-others$/, (m, body, path) => {
      // From a session not in good standing only the others not in good
      // standing, and while it is under an hour old none older than itself.
      const cur = currentSession();
      const ended = activeSessions().filter((s) => s.id !== cur.id && (cur.good_standing
        || (!s.good_standing && !(youngerThanHour(cur) && Date.parse(s.created_at) < Date.parse(cur.created_at)))));
      ended.forEach((s) => endSession(s, "end_others"));
      return { ended: ended.length };
    }],
    // §2.6.3: a held address change, approved or rejected by what it names.
    ["POST", /^\/me\/notification-settings\/email\/address-change\/(approve|reject)$/, (m, body, path) => {
      const email = fixtures()["notifications.json"].settings.email;
      const held = email && email.address_change;
      const cur = currentSession();
      if (!cur.good_standing) fail(403, "forbidden", "not in good standing", path, { reason: "not_in_good_standing" });
      if (m[1] === "approve" && Date.now() - Date.parse(cur.created_at) < 24 * 3600 * 1000) fail(403, "forbidden", "this session is too new", path, { reason: "session_too_new" });
      if (!held || held.id !== body.id || held.address !== body.address) fail(409, "conflict", "not the held change", path);
      if (m[1] === "approve") Object.assign(email, { pending_address: held.address });
      email.address_change = null;
      return fixtures()["notifications.json"].settings;
    }],
    ["POST", /^\/auth\/login$/, (m, body, path) => {
      if (body.handle !== me().member.handle || !body.password
        || (fixturePassword !== null && body.password !== fixturePassword)) {
        fail(401, "unauthenticated", "Handle or password is wrong", path);
      }
      fixtureSignedIn = true;
      return { member: me().member, next: body.next || "/" };
    }],
    // §2.7.1: always 202 for a well-formed request; what follows is in the mail.
    ["POST", /^\/auth\/register$/, (m, body, path) => {
      const fields = {};
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(body.address || ""))) fields.address = "invalid";
      if ([...(body.password || "")].length < 12) fields.password = "too_short";
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      return { expires_in: 86400 };
    }],
    // docs/api.md §2.1: any password signs in until one is set here; then
    // that one. The new one has at least 12 characters, as the hub wants.
    ["POST", /^\/auth\/password$/, (m, body, path) => {
      if (!body.current || (fixturePassword !== null && body.current !== fixturePassword)) {
        fail(400, "invalid", "the current password is wrong", path, { fields: { current: "mismatch" } });
      }
      if ([...(body.new || "")].length < 12) fail(400, "invalid", "a password has at least 12 characters", path, { fields: { new: "too_short" } });
      fixturePassword = body.new;
      return { member: me().member };
    }],
    ["POST", /^\/auth\/logout$/, () => {
      fixtureSignedIn = false;
      return { member: me().member };
    }],
    // open_requests is derived from the request fixtures, so that answers
    // given in this tab show in the counts.
    ["GET", /^\/me$/, () => {
      const data = me();
      data.projects.forEach((p) => {
        p.open_requests = openFor(p.slug).length;
        p.state = project(p.slug, "").state;
        // §5.1: the logo as the project view has it, without its source.
        const logo = project(p.slug, "").logo;
        if (logo) p.logo = { available: !!logo.available, etag: logo.available ? logo.etag : null };
      });
      data.server_time = nowIso();
      // A renamed project: its directory stays, its slug is the project's now (§6.25).
      return Object.assign({}, data, { projects: data.projects.map((p) => Object.assign({}, p, { slug: project(p.slug, "").slug })) });
    }],
    // §18.2: the human's notifications. inbox counts the open requests as
    // /me does; chat and the rest count the unread items of their kind
    // (the hub's chat count is the conversations' unread, which the
    // fixtures do not keep apart).
    ["GET", /^\/me\/notifications$/, (m, body, path, query) => {
      const n = fixtures()["notifications.json"];
      const limit = query.get("limit") === null ? 20 : Number(query.get("limit"));
      if (!Number.isInteger(limit) || limit < 0 || limit > 50) fail(400, "invalid", "limit is 0 to 50", path, { fields: { limit: "invalid" } });
      const { counts, by_project: byProject } = notificationCounts();
      const kinds = query.get("kind") ? query.get("kind").split(",") : null;
      (kinds || []).forEach((k) => {
        if (!KINDS.includes(k)) fail(400, "invalid", "the request does not validate", path, { fields: { kind: "unknown" } });
      });
      const projects = query.get("project") ? query.get("project").split(",") : null;
      const allowed = n.settings.browser.content || {};
      // content only on chat and mention, and only when the settings allow it (§18.2).
      const view = (x) => {
        const out = Object.assign({}, x);
        delete out._text;
        delete out.open_matter;
        if (x._text && allowed[x.kind]) out.content = x._text.replace(/\s+/g, " ").slice(0, 120);
        return out;
      };
      const items = n.items.filter((x) => (query.get("unread") !== "true" || !x.read)
        && (!kinds || kinds.includes(x.kind)) && (!projects || (x.project && projects.includes(x.project.full_name))));
      const after = query.get("after");
      const head = headOf(n.items);
      if (after !== null) {
        if (!limit) return { counts, by_project: byProject, items: [], next_cursor: null, next_after: after, server_time: nowIso() };
        const past = items.filter((x) => pastOf(x, after)).sort(inOrder);
        const listed = past.slice(0, limit);
        const [a, b] = parts(after);
        const [ha, hb] = parts(head);
        // Cut: moved by what was listed; else the head, never below after.
        const next = past.length > limit
          ? Math.max(a, ...listed.filter((x) => !x.record).map((x) => x.seq)) + "." + Math.max(b, ...listed.filter((x) => x.record).map(recordNo))
          : Math.max(a, ha) + "." + Math.max(b, hb);
        return { counts, by_project: byProject, items: listed.map(view), next_cursor: null, next_after: next, server_time: nowIso() };
      }
      const offset = Number(query.get("cursor") || 0);
      const ordered = items.slice().sort(inOrder).reverse();
      const listed = ordered.slice(offset, offset + limit);
      return { counts, by_project: byProject, items: listed.map(view),
        next_cursor: limit && offset + limit < ordered.length ? String(offset + limit) : null,
        next_after: head, server_time: nowIso() };
    }],
    // §18.3: by ids, or everything up to a seq (of one kind or project).
    ["POST", /^\/me\/notifications\/read$/, (m, body, path) => {
      const n = fixtures()["notifications.json"];
      if (("ids" in body) === ("up_to" in body)) fail(400, "invalid", "ids or up_to", path, { fields: { body: "invalid" } });
      // A kind outside the four, one removed earlier included, is unknown (§18.3).
      if ("kind" in body && !KINDS.includes(body.kind)) fail(400, "invalid", "the request does not validate", path, { fields: { kind: "unknown" } });
      // up_to never reaches a security item: those only by id, from a
      // session allowed to (§18.3); a confirmed sign-in is in good standing.
      n.items.forEach((x) => {
        if (body.ids && body.ids.includes(x.id) && x.kind === "security") {
          if (!mayMarkSecurity(x)) return;
          const reported = x.target && x.target.type === "session" && fixtures()["sessions.json"].items.find((s) => s.id === x.target.id);
          if (reported) reported.good_standing = true;
          x.read = true;
          return;
        }
        if (body.ids ? body.ids.includes(x.id)
          : x.kind !== "security" && !pastOf(x, body.up_to) && (!body.kind || x.kind === body.kind)
            && (!body.project || (x.project && x.project.full_name === body.project))) x.read = true;
      });
      return notificationCounts();
    }],
    // §18.4: the account's settings; a PATCH merges what it names.
    // §19.4: the human's preferences, their versions, the projects that read them.
    ["GET", /^\/me\/preferences$/, () => Object.assign({}, prefs().current, { projects: prefs().projects })],
    ["PUT", /^\/me\/preferences$/, (m, body, path) => {
      const text = typeof body.markdown === "string" ? body.markdown : null;
      if (text === null) fail(400, "invalid", "markdown is required", path, { fields: { markdown: "required" } });
      if (utf8Bytes(text) > 8 * 1024) fail(400, "invalid", "over 8 KiB", path, { fields: { markdown: "too_long" } });
      const now = prefs().current;
      if (body.base_version !== undefined && body.base_version !== now.version) {
        fail(409, "conflict", "the preferences changed", path, { current_version: now.version, base_version: body.base_version });
      }
      return Object.assign({}, writePrefs(text, { kind: "human", id: me().member.id, handle: me().member.handle }, null, null), { projects: prefs().projects });
    }],
    ["GET", /^\/me\/preferences\/versions$/, (m, body, path, query) => {
      const limit = Number(query.get("limit") || 50);
      const before = query.get("cursor") === null ? Infinity : Number(query.get("cursor"));
      const all = prefs().versions.filter((v) => v.version < before);
      const page = all.slice(0, limit);
      return { items: page, next_cursor: all.length > limit ? String(page[page.length - 1].version) : null };
    }],
    ["PUT", /^\/me\/preferences\/projects\/([^/]+)\/([^/]+)$/, (m, body, path) => {
      const entry = prefs().projects.find((p) => p.full_name === decodeURIComponent(m[1]) + "/" + decodeURIComponent(m[2]));
      if (!entry) fail(404, "not_found", "Not found", path);
      if (typeof body.include !== "boolean") fail(400, "invalid", "include is a boolean", path, { fields: { include: "bool_type" } });
      entry.include = body.include;
      return { slug: entry.slug, full_name: entry.full_name, include: entry.include };
    }],
    ["GET", /^\/me\/notification-settings$/, () => fixtures()["notifications.json"].settings],
    // §5.2 "Meat proxy": the human's own switch, a boolean; nobody sets it for another.
    ["PATCH", /^\/me$/, (m, body, path) => {
      if (me().member.kind !== "human") fail(403, "forbidden", "a human's own change", path, { reason: "humans_only" });
      if ("meat_proxy" in body && typeof body.meat_proxy !== "boolean") fail(400, "invalid", "the request does not validate", path, { fields: { meat_proxy: "type" } });
      if ("meat_proxy" in body) me().member.meat_proxy = body.meat_proxy;
      return Object.assign({}, me().member);
    }],
    // §6.26 Organisations: humans only; a caller who is not a member gets not_found,
    // one whose role does not allow the call forbidden (org_role).
    ["GET", /^\/orgs$/, () => ({ items: orgsData().items.filter((o) => orgRole(o)).map(orgView) })],
    ["POST", /^\/orgs$/, (m, body, path) => {
      humanOnly(path);
      const fields = {};
      if (!/^[a-z0-9][a-z0-9-]{1,30}$/.test(body.handle || "")) fields.handle = "format";
      else if (ORG_RESERVED.includes(body.handle)) fields.handle = "reserved";
      else if (orgsData().items.some((o) => o.handle === body.handle || (o.aliases || []).includes(body.handle)) || body.handle === me().member.handle) fields.handle = "taken";
      const name = String(body.display_name || "").trim();
      if (!name || name.length > 64) fields.display_name = "length";
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      const org = { id: "org-f" + String(orgsData().items.length + 1).padStart(11, "0"), handle: body.handle, display_name: name, avatar_url: null, aliases: [],
        created_at: nowIso(), members_create_projects: false, public_page: "off" };
      orgsData().items.push(org);
      orgsData().members[org.id] = [{ id: me().member.id, handle: me().member.handle, display_name: me().member.display_name, avatar_url: null, role: "owner", joined_at: nowIso() }];
      orgsData().invitations[org.id] = [];
      return orgView(org);
    }],
    ["GET", /^\/orgs\/([^/]+)$/, (m, body, path) => orgView(orgOf(m[1], path))],
    ["PATCH", /^\/orgs\/([^/]+)$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      orgNeeds(org, ["owner"], path);
      const fields = {};
      if ("display_name" in body && (!String(body.display_name).trim() || String(body.display_name).length > 64)) fields.display_name = "length";
      if ("public_page" in body && !["on", "off"].includes(body.public_page)) fields.public_page = "unknown";
      if ("handle" in body && body.handle !== org.handle) {
        if (!/^[a-z0-9][a-z0-9-]{1,30}$/.test(body.handle || "")) fields.handle = "format";
        else if (ORG_RESERVED.includes(body.handle)) fields.handle = "reserved";
        else if (orgsData().items.some((o) => o !== org && (o.handle === body.handle || (o.aliases || []).includes(body.handle)))) fields.handle = "taken";
      }
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      if ("handle" in body && body.handle !== org.handle) { org.aliases = (org.aliases || []).concat(org.handle); org.handle = body.handle; }
      ["display_name", "members_create_projects", "public_page"].forEach((k) => { if (k in body) org[k] = k === "display_name" ? String(body[k]).trim() : body[k]; });
      return orgView(org);
    }],
    ["DELETE", /^\/orgs\/([^/]+)$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      orgNeeds(org, ["owner"], path);
      if (body.confirm !== org.handle) fail(400, "invalid", "the request does not validate", path, { fields: { confirm: "mismatch" } });
      const all = fixtures();
      const owned = Object.keys(all).filter((k) => /\/project\.json$/.test(k) && all[k].owner && all[k].owner.id === org.id).map((k) => k.split("/")[0]);
      if (owned.length) fail(409, "namespace_owner", "the organisation still owns projects", path, { projects: owned });
      orgsData().items = orgsData().items.filter((o) => o !== org);
      return null;
    }],
    ["PUT", /^\/orgs\/([^/]+)\/avatar$/, avatarRoute(ownerOrg)],
    ["DELETE", /^\/orgs\/([^/]+)\/avatar$/, avatarRoute(ownerOrg)],
    ["GET", /^\/orgs\/([^/]+)\/members$/, (m, body, path) => ({ items: orgsData().members[orgOf(m[1], path).id].slice() })],
    ["PATCH", /^\/orgs\/([^/]+)\/members\/([^/]+)$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      const list = orgsData().members[org.id];
      const target = list.find((x) => x.id === m[2]);
      if (!target) fail(404, "not_found", "Not found", path);
      if (!["owner", "admin", "member"].includes(body.role)) fail(400, "invalid", "the request does not validate", path, { fields: { role: "unknown" } });
      const mine = orgRole(org);
      if (mine !== "owner" && (mine !== "admin" || target.role === "owner" || body.role === "owner")) fail(403, "forbidden", "not for your role", path, { reason: "org_role" });
      if (target.role === "owner" && body.role !== "owner" && list.filter((x) => x.role === "owner").length === 1) fail(409, "org_last_owner", "the last owner", path, { orgs: [org.handle] });
      target.role = body.role;
      return target;
    }],
    ["DELETE", /^\/orgs\/([^/]+)\/members\/([^/]+)$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      const list = orgsData().members[org.id];
      const target = list.find((x) => x.id === m[2]);
      if (!target) fail(404, "not_found", "Not found", path);
      const mine = orgRole(org);
      const self = target.id === me().member.id;
      if (!self && mine !== "owner" && (mine !== "admin" || target.role === "owner")) fail(403, "forbidden", "not for your role", path, { reason: "org_role" });
      if (target.role === "owner" && list.filter((x) => x.role === "owner").length === 1) fail(409, "org_last_owner", "the last owner", path, { orgs: [org.handle] });
      orgsData().members[org.id] = list.filter((x) => x !== target);
      return null;
    }],
    ["GET", /^\/orgs\/([^/]+)\/members\/invitations$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      orgNeeds(org, ["owner", "admin"], path);
      return { items: orgsData().invitations[org.id].slice() };
    }],
    ["POST", /^\/orgs\/([^/]+)\/members\/invitations$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      orgNeeds(org, ["owner", "admin"], path);
      if (!["owner", "admin", "member"].includes(body.role)) fail(400, "invalid", "the request does not validate", path, { fields: { role: "unknown" } });
      if (body.role === "owner" && orgRole(org) !== "owner") fail(403, "forbidden", "not for your role", path, { reason: "org_role" });
      const handle = String(body.handle || "").replace(/^@/, "");
      if (orgsData().members[org.id].some((x) => x.handle === handle)) fail(400, "invalid", "the request does not validate", path, { fields: { handle: "member" } });
      if (orgsData().invitations[org.id].some((x) => x.handle === handle)) fail(400, "invalid", "the request does not validate", path, { fields: { handle: "invited" } });
      const at = new Date();
      const item = { id: "oinv-f" + String(++orgInviteSerial).padStart(3, "0"), handle, role: body.role, invited_by: { id: me().member.id, handle: me().member.handle },
        created_at: nowIso(),
        expires_at: new Date(at.getTime() + 14 * 86400000).toISOString().replace(/\.\d{3}Z$/, "Z") };
      orgsData().invitations[org.id].push(item);
      return item;
    }],
    ["DELETE", /^\/orgs\/([^/]+)\/members\/invitations\/([^/]+)$/, (m, body, path) => {
      const org = orgOf(m[1], path);
      orgNeeds(org, ["owner", "admin"], path);
      // An invitation for the role owner is withdrawn by an owner only.
      const item = orgsData().invitations[org.id].find((x) => x.id === m[2]);
      if (item && item.role === "owner" && orgRole(org) !== "owner") fail(403, "forbidden", "not for your role", path, { reason: "org_role" });
      orgsData().invitations[org.id] = orgsData().invitations[org.id].filter((x) => x.id !== m[2]);
      return null;
    }],
    // §2.9 Your data: the export, and a deletion request withdrawn or asked again.
    // The fixture hub needs no proof: the step-up is the smoke test's to answer.
    ["GET", /^\/me\/export$/, (m, body, path) => {
      if (me().member.kind !== "human") fail(403, "forbidden", "a human's own data", path, { reason: "humans_only" });
      const at = nowIso();
      return { format: 1, exported_at: at, account: { handle: me().member.handle, display_name: me().member.display_name },
        memberships: me().projects.map((p) => ({ project: p.full_name, trust: p.trust, role: p.role })) };
    }],
    ["POST", /^\/me\/deletion$/, (m, body, path) => {
      if (me().member.kind !== "human") fail(403, "forbidden", "a human's own account", path, { reason: "humans_only" });
      if (body.confirm !== me().member.handle) fail(400, "invalid", "the request does not validate", path, { fields: { confirm: "mismatch" } });
      const at = new Date();
      me().member.deletion = { requested_at: at.toISOString().replace(/\.\d{3}Z$/, "Z"),
        expires_at: new Date(at.getTime() + 86400000).toISOString().replace(/\.\d{3}Z$/, "Z") };
      return { deletion: me().member.deletion };
    }],
    ["DELETE", /^\/me\/deletion$/, () => {
      me().member.deletion = null;
      return { deletion: null };
    }],
    ["POST", /^\/auth\/reauthenticate$/, (m, body, path) => {
      if (body.password !== "correct horse") fail(400, "invalid", "the request does not validate", path, { fields: { password: "mismatch" } });
      return { valid_until: new Date(Date.now() + 600000).toISOString().replace(/\.\d{3}Z$/, "Z") };
    }],
    ["POST", /^\/auth\/second-factor\/verify$/, (m, body, path) => {
      if (body.code !== "123456" && body.recovery_code !== "abcde-fghij") fail(400, "code_invalid", "the code is not valid", path);
      return { valid_until: new Date(Date.now() + 600000).toISOString().replace(/\.\d{3}Z$/, "Z") };
    }],
    ["PATCH", /^\/me\/notification-settings$/, (m, body, path) => {
      const set = fixtures()["notifications.json"].settings;
      if (body.email && "language" in body.email) {
        if (!["en", "de"].includes(body.email.language)) fail(400, "invalid", "unknown language", path);
        set.email.language = body.email.language;
      }
      const b = body.browser || {};
      if ("enabled" in b && typeof b.enabled !== "boolean") fail(400, "invalid", "enabled is a boolean", path, { fields: { "browser.enabled": "invalid" } });
      if ("enabled" in b) set.browser.enabled = b.enabled;
      Object.entries(b.kinds || {}).forEach(([k, v]) => {
        if (!(k in set.browser.kinds)) fail(400, "invalid", "unknown kind", path, { fields: { ["browser.kinds." + k]: "unknown" } });
        set.browser.kinds[k] = !!v;
      });
      Object.entries(b.content || {}).forEach(([k, v]) => {
        if (!(k in set.browser.content)) fail(400, "invalid", "no content for this kind", path, { fields: { ["browser.content." + k]: "unknown" } });
        set.browser.content[k] = !!v;
      });
      return set;
    }],
    // A deleted profile (tombstone) is never listed (§6.3).
    ["GET", /^\/agents$/, () => Object.assign({}, fixtures()["agents.json"], { items: fixtures()["agents.json"].items.filter((a) => !a.deleted_at) })],
    // §6.3: the owner deletes a profile. In use (an active membership) only with
    // ?cascade=true, which ends every membership as DELETE …/members/{id} does;
    // then a tombstone with deleted_at, no avatar, no memberships. Again: 200 as it is.
    ["DELETE", /^\/agents\/([^/]+)$/, (m, body, path, query) => {
      const agent = (fixtures()["agents.json"] || { items: [] }).items.find((a) => a.id === m[1]);
      if (!agent || agent.owner_id !== me().member.id || me().member.kind !== "human") fail(404, "not_found", "Not found", path);
      if (agent.deleted_at) return agent;
      const memberships = (agent.memberships || []).map((x) => {
        const key = fixtureSlugs().find((k) => fullOf(k) === x.project);
        return { key, project: x.project, member_id: agent.id, trust: x.trust, role: x.role };
      });
      if (memberships.length && !(query && query.get("cascade") === "true")) {
        fail(409, "profile_in_use", "the profile is in use", path, { memberships: memberships.map(({ key, ...rest }) => rest), placements: [] });
      }
      const at = nowIso();
      memberships.forEach(({ key }) => {
        if (!key || !fixtures()[key + "/members.json"]) return;
        const list = file(key, "members.json", path);
        const target = list.items.find((x) => x.id === agent.id);
        if (!target) return;
        ((fixtures()[key + "/credentials.json"] || {})[target.id] || { items: [] }).items.forEach((c) => {
          if (!c.revoked_at) { c.revoked_at = at; c.revoked_by = me().member.id; c.revoked_reason = "member_removed"; c.session_id = null; }
        });
        (fixtures()[key + "/tasks.json"] || { items: [] }).items.forEach((t) => { if (t.claim && t.claim.holder === target.id) t.claim = null; });
        list.items = list.items.filter((x) => x !== target);
        list.items.forEach((x) => { if (x.reports_to === target.id) x.reports_to = null; });
        list.removed = (list.removed || []).concat(Object.assign({}, target, { removed_at: at }));
      });
      Object.assign(agent, { deleted_at: at, memberships: [], avatar_url: null, avatar_source: null });
      return agent;
    }],
    ["GET", /^\/health$/, () => ({ status: "ok", version: "fixture", api: "v1", database: { reachable: true, revision: "fixture-head", head: "fixture-head" } })],
    ["GET", /^\/admin\/settings\/mail$/, (m, body, path) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path);
      return fixtures()["admin-mail.json"];
    }],
    ["PATCH", /^\/admin\/settings\/mail$/, (m, body, path) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path);
      const value = fixtures()["admin-mail.json"];
      Object.entries(body).forEach(([k]) => { if (value[k] && value[k].source === "env") fail(400, "invalid", "Set by the environment", path, { fields: { [k]: "set_by_environment" } }); });
      Object.entries(body).forEach(([k, v]) => {
        if (k === "enabled") value.enabled = v;
        else if (k === "password") value.password = { set: v !== null, source: "admin" };
        else value[k] = { value: v, source: v === null ? "default" : "admin" };
      });
      value.last_test = null; return value;
    }],
    ["POST", /^\/admin\/settings\/mail\/test$/, (m, body, path) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path);
      if (!body.to) fail(400, "invalid", "Recipient required", path);
      const value = fixtures()["admin-mail.json"];
      value.last_test = { ok: true, stage: null, smtp_code: 250, detail: null, at: nowIso() }; return value.last_test;
    }],
    // §16.1: the instance admin's list, by handle, filtered and paged.
    ["GET", /^\/admin\/users$/, (m, body, path, query) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path, { scope: "instance:admin" });
      const q = query.get("q");
      if (q !== null && ([...q].length < 1 || [...q].length > 64)) fail(400, "invalid", "q is 1 to 64 characters", path, { fields: { q: "string_too_long" } });
      const d = query.get("disabled");
      if (d !== null && d !== "true" && d !== "false") fail(400, "invalid", "disabled is true or false", path, { fields: { disabled: "not_boolean" } });
      const all = fixtures()["admin-users.json"].items
        .filter((u) => !q || (u.handle + "\n" + u.display_name).toLowerCase().includes(q.toLowerCase()))
        .filter((u) => d === null || String(u.disabled) === d)
        .sort((a, b) => a.handle.localeCompare(b.handle));
      // §1.4: limit 1–200, the cursor one this list gave out.
      const limit = Number(query.get("limit") || 50);
      const start = Number(query.get("cursor") || 0);
      if (!Number.isInteger(limit) || limit < 1 || limit > 200) fail(400, "invalid", "limit is 1 to 200", path, { fields: { limit: "out_of_range" } });
      if (!Number.isInteger(start) || start < 0) fail(400, "invalid", "not a cursor of this list", path, { fields: { cursor: "invalid_cursor" } });
      const items = all.slice(start, start + limit);
      return { items, next_cursor: start + limit < all.length ? String(start + limit) : null };
    }],
    // Runners (docs/api.md §15.2–§15.3), instance level.
    ["GET", /^\/runners$/, () => ({ items: runnersFile().items.filter((r) => !r.removed_at), next_cursor: null })],
    // §15.6 placements: the list, desired, restart; who may as the hub
    // checks it (a human with members:admin who owns the runner, or the
    // agent profile's owner).
    ["GET", /^\/projects\/([^/]+)\/placements$/, (m, body, path) => {
      project(m[1], path);
      return { items: placementsOf(m[1]).filter((p) => p.active), next_cursor: null };
    }],
    ["PATCH", /^\/projects\/([^/]+)\/placements\/([^/]+)$/, (m, body, path) => {
      const p = placementFor(m[1], m[2], path);
      if (!["running", "stopped"].includes(body.desired)) fail(400, "invalid", "desired is running or stopped", path, { fields: { desired: "unknown" } });
      if (body.desired === "running" && ["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      p.desired = body.desired;
      p.updated_by = me().member.id; p.updated_at = nowIso();
      return p;
    }],
    ["POST", /^\/projects\/([^/]+)\/placements\/([^/]+)\/restart$/, (m, body, path) => {
      const p = placementFor(m[1], m[2], path);
      const creds = (fixtures()[m[1] + "/credentials.json"] || {})[p.agent.id];
      const cred = creds && creds.items.find((c) => c.id === p.credential_id);
      if (body.rejoin && !(cred && cred.revoked_at)) {
        fail(400, "invalid", "the placement's credential is not revoked", path, { fields: { rejoin: "credential_not_revoked" } });
      }
      p.generation += 1; p.desired = "running"; p.rejoin = !!body.rejoin; p.reported_current = false;
      p.updated_by = me().member.id; p.updated_at = nowIso();
      return p;
    }],
    ["GET", /^\/runners\/enrollments$/, () => ({ items: fixtures()["runner-enrollments.json"].items.slice().reverse(), next_cursor: null })],
    ["POST", /^\/runners\/enrollments$/, (m, body, path) => {
      const ttl = body.ttl_seconds === undefined ? 900 : body.ttl_seconds;
      if (ttl < 60 || ttl > 900) fail(400, "invalid", "ttl out of range", path, { fields: { ttl_seconds: "out_of_range" } });
      let runnerId = null;
      let name = body.name || null;
      if (body.runner_id) {
        runnerOf(body.runner_id, path);
        runnerId = body.runner_id;
        name = null;
      } else {
        if (!name || !/^[a-z0-9][a-z0-9-]{1,30}$/.test(name)) fail(400, "invalid", "a runner needs a name", path, { fields: { name: name ? "string_pattern_mismatch" : "missing" } });
        if (runnersFile().items.some((r) => !r.removed_at && r.name === name)) fail(400, "invalid", "you have a runner of that name", path, { fields: { name: "taken" } });
      }
      const admin = me().projects.filter((p) => ["owner", "admin"].includes(p.trust)).map((p) => p.full_name);
      (body.attach || []).forEach((slug) => { if (!admin.includes(slug)) fail(403, "forbidden", "members:admin needed in " + slug, path, { scope: "members:admin" }); });
      const id = localId("renr");
      const expires = new Date(Date.now() + ttl * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
      fixtures()["runner-enrollments.json"].items.push({ id, runner_id: runnerId, name, attach: body.attach || [], created_at: nowIso(),
        expires_at: expires, used_at: null, burned: false, revoked_at: null });
      const url = "https://maity.example/r/FIXTURE-" + id;
      return { id, runner_id: runnerId, pair_url: url, code: "FIXT-URE0-RUNR", pair_line: "maity runner pair " + url + " --code FIXT-URE0-RUNR", expires_at: expires };
    }],
    ["DELETE", /^\/runners\/enrollments\/([^/]+)$/, (m, body, path) => {
      const e = fixtures()["runner-enrollments.json"].items.find((x) => x.id === m[1]);
      if (!e) fail(404, "not_found", "no such enrollment", path);
      if (e.used_at || e.burned || Date.parse(e.expires_at) <= Date.now()) {
        if (!e.revoked_at) fail(409, "invalid_transition", "used, burned or expired", path);
      }
      e.revoked_at = e.revoked_at || nowIso();
      return e;
    }],
    ["GET", /^\/runners\/([^/]+)$/, (m, body, path) => runnerOf(m[1], path)],
    ["PATCH", /^\/runners\/([^/]+)$/, (m, body, path) => {
      const r = runnerOf(m[1], path);
      if (r.removed_at) fail(409, "invalid_transition", "the runner was removed", path, { from: "removed", to: null });
      if (runnersFile().items.some((x) => x !== r && !x.removed_at && x.name === body.name)) fail(400, "invalid", "you have a runner of that name", path, { fields: { name: "taken" } });
      r.name = body.name;
      r.updated_at = nowIso();
      return r;
    }],
    ["POST", /^\/runners\/([^/]+)\/revoke$/, (m, body, path) => {
      const r = runnerOf(m[1], path);
      if (r.credential && !r.credential.revoked_at) {
        r.credential.revoked_at = nowIso();
        r.credential.revoked_reason = body.reason || "revoked";
      }
      r.credential_state = r.credential ? "revoked" : "none";
      r.presence = "offline";
      r.listening = false;
      return r;
    }],
    ["DELETE", /^\/runners\/([^/]+)$/, (m, body, path) => {
      const r = runnerOf(m[1], path);
      if (!r.removed_at) {
        if (r.credential && !r.credential.revoked_at) { r.credential.revoked_at = nowIso(); r.credential.revoked_reason = "runner_removed"; }
        r.credential_state = "revoked";
        r.removed_at = nowIso();
        r.projects = [];
        runnersFile().attachments.filter((a) => a.runner_id === r.id && !a.detached_at).forEach((a) => { a.detached_at = r.removed_at; });
      }
      return Object.assign({}, r, { still_running: (runnersFile().still_running || {})[r.id] || [] });
    }],
    // Attachments (docs/api.md §15.4). The runner's `projects` follow them.
    ["GET", /^\/projects\/([^/]+)\/runners$/, (m, body, path) => {
      project(m[1], path);
      return { items: activeAttachments(m[1]).map(attachmentView), next_cursor: null };
    }],
    ["POST", /^\/projects\/([^/]+)\/runners$/, (m, body, path) => {
      project(m[1], path);
      const r = runnersFile().items.find((x) => x.id === body.runner_id && !x.removed_at);
      if (!r || r.owner_id !== me().member.id) fail(400, "invalid", "attach one of your own runners", path, { fields: { runner_id: "not_yours" } });
      const open = activeAttachments(m[1]).find((a) => a.runner_id === r.id);
      if (open) fail(409, "already_attached", "the runner is attached already", path, { attachment: attachmentView(open) });
      const a = { id: "ratt-" + String(++attachSerial).padStart(4, "0") + "f", runner_id: r.id, project: fullOf(m[1]),
        attached_by: me().member.id, attached_at: nowIso(), detached_at: null };
      runnersFile().attachments.push(a);
      r.projects = (r.projects || []).concat(fullOf(m[1]));
      return attachmentView(a);
    }],
    ["DELETE", /^\/projects\/([^/]+)\/runners\/([^/]+)$/, (m, body, path) => {
      const all = runnersFile().attachments.filter((x) => x.project === fullOf(m[1]) && x.runner_id === m[2]);
      if (!all.length) fail(404, "not_found", "the runner was never attached here", path);
      const a = all.find((x) => !x.detached_at) || all[all.length - 1];
      if (!a.detached_at) {
        a.detached_at = nowIso();
        const r = runnerOf(m[2], path);
        r.projects = (r.projects || []).filter((s) => s !== fullOf(m[1]));
        const counts = (runnersFile().active_placements || {})[r.id];
        if (counts) delete counts[fullOf(m[1])];
      }
      return attachmentView(a);
    }],
    // The cross-project inbox: every open request waiting for this human,
    // each with its project.
    // Personal requests (§7) are the human's own, listed here only.
    ["GET", /^\/requests$/, () => ({
      items: me().projects.flatMap((p) => openFor(p.slug).map((r) => Object.assign(
        { project: { slug: project(p.slug, "").slug, full_name: p.full_name, name: p.name, state: project(p.slug, "").state } }, r)))
        // A list shows no proposal (§7, §19.4): GET /requests/{id} has it.
        .concat(personalRequests().filter((r) => r.status === "open").map((r) => {
          const listed = Object.assign({}, r);
          delete listed.memory_proposal;
          return listed;
        })),
      next_cursor: null,
    })],
    ["GET", /^\/requests\/([^/]+)$/, (m, body, path) => {
      const req = personalRequests().find((r) => r.id === m[1]);
      if (!req) fail(404, "not_found", "Not found", path);
      return personalView(req);
    }],
    ["POST", /^\/requests\/([^/]+)\/(answer|withdraw)$/, (m, body, path) => {
      const req = personalRequests().find((r) => r.id === m[1]);
      if (!req) fail(404, "not_found", "Not found", path);
      if (req.status !== "open") fail(409, "request_not_open", "Request is not open", path);
      const proposal = req.memory_proposal && req.memory_proposal.store === "preferences" ? req.memory_proposal : null;
      const edited = "markdown" in body || "base_version" in body;
      if (edited && !proposal) fail(400, "invalid", "not a preference proposal", path, { fields: { markdown: "not_a_preference_proposal" } });
      if (proposal && m[2] === "answer" && body.reply_id === "go") {
        if (edited && !("markdown" in body && "base_version" in body)) fail(400, "invalid", "markdown and base_version together", path, { fields: { markdown: "go_with_markdown_and_base_version" } });
        const now = prefs().current.version;
        const base = edited ? body.base_version : proposal.base_version;
        if (base !== now) fail(409, "conflict", "the preferences changed", path, { current_version: now, base_version: base });
        if (edited && utf8Bytes(body.markdown) > 8 * 1024) fail(400, "invalid", "over 8 KiB", path, { fields: { markdown: "too_long" } });
        const agent = { kind: "agent", member_id: req.asked_by.member_id, handle: "agent-a", project: req.project.full_name, request_id: req.id };
        const human = { kind: "human", id: me().member.id, handle: me().member.handle };
        const v = edited
          ? writePrefs(body.markdown, human, agent, null)
          : writePrefs(proposal.markdown, { kind: "agent", id: req.asked_by.member_id, handle: "agent-a" }, agent, human);
        proposal.result = { version: v.version, edited };
      } else if (edited) {
        fail(400, "invalid", "markdown and base_version only with go", path, { fields: { markdown: "go_with_markdown_and_base_version" } });
      }
      const at = nowIso();
      req.status = m[2] === "answer" ? "answered" : "withdrawn";
      req.answered_at = at;
      req.answer = m[2] === "answer"
        ? { reply_id: body.reply_id || null, text: body.text || null, talk: !!body.talk, by: me().member.id, on_behalf_of: null, at, conversation_id: null }
        : null;
      return req;
    }],
    // The forge rule as the hub applies it, with github.com as the one
    // configured forge.
    ["POST", /^\/projects$/, (m, body, path) => {
      const fields = {};
      if (!SLUG.test(body.slug || "")) fields.slug = "string_pattern_mismatch";
      // §6.25: a slug is never a route word, and taken once in one's namespace.
      else if (ROUTE_WORDS.includes(body.slug)) fields.slug = "reserved";
      else if (fixtures()[body.slug + "/project.json"] || slugOfFull(me().member.handle + "/" + body.slug)) fields.slug = "taken";
      if (!body.name || !body.name.trim()) fields.name = "string_too_short";
      const url = body.repository ? String(body.repository.url || "").replace(/\/+$/, "") : null;
      if (url !== null && !/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/.test(url)) {
        fields["repository.url"] = "not_a_configured_forge";
      }
      const preset = body.policy && body.policy.preset ? body.policy.preset : "hierarchical";
      if (!PRESETS[preset]) fields["policy.preset"] = "unknown";
      // §6.1, §6.21: the provider (keep_the_why its alias) and the options.
      const provider = body.memory ? body.memory.provider : body.keep_the_why === false ? "none" : "keep-the-why";
      if (!["keep-the-why", "none"].includes(provider)) fields["memory.provider"] = "unknown_provider";
      const given = body.setup || {};
      Object.keys(given).forEach((k) => {
        if (!SETUP_CARDS.some(([key]) => key === k)) fields["setup." + k] = "unknown_field";
        else if (typeof given[k] !== "boolean") fields["setup." + k] = "not_a_boolean";
      });
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      const ktw = provider === "keep-the-why";
      const setup = { keep_the_why_init: ktw && given.keep_the_why_init !== false, keep_the_why_badge: ktw && given.keep_the_why_badge !== false,
        maity_badge: given.maity_badge === true, cards: null };
      const owner = me().member;
      const created = {
        id: localId("prj"), slug: body.slug, owner: { id: owner.id, handle: owner.handle }, full_name: owner.handle + "/" + body.slug,
        legacy_slug: null, aliases: [],
        name: body.name, state: "build", state_note: null, state_changed_at: nowIso(),
        repository: url === null ? null : {
          url, default_branch: body.repository.default_branch || "main", forge: "github", probe_configured: false,
        },
        memory: { provider }, keep_the_why: ktw, setup,
        policy: Object.assign({}, PRESETS[preset], {
          preset, contract_arbiter: PRESETS[preset].contract_arbiter || owner.id,
          // The creator's Maity badge switches the badge on at creation (§6.20).
          badge: setup.maity_badge ? "members" : "off",
        }),
        absence: null, settings: { release_checklist: [] }, rules_version: 1, created_at: nowIso(),
      };
      const data = fixtures();
      const empty = { items: [], next_cursor: null };
      data[body.slug + "/project.json"] = created;
      data[body.slug + "/members.json"] = { items: [Object.assign({}, owner, {
        trust: "owner", role: "coder", reports_to: null, areas: ["/"], capabilities: [], last_seen_at: nowIso(),
        presence: "online", paused: null, joined_at: nowIso(),
      })], next_cursor: null };
      ["requests", "tasks", "joins"].forEach((name) => { data[body.slug + "/" + name + ".json"] = Object.assign({}, empty); });
      data[body.slug + "/credentials.json"] = {};
      data[body.slug + "/conversations.json"] = {};
      if (url !== null) makeSetupCards(body.slug, setup, owner.id, url);
      me().projects.push({ slug: body.slug, full_name: created.full_name, name: body.name, state: "build", trust: "owner", role: "coder", open_requests: 0 });
      return created;
    }],
    ["GET", /^\/projects\/([^/]+)$/, (m, body, path) => project(m[1], path)],
    ["GET", /^\/projects$/, () => ({ items: me().projects.map((p) => project(p.slug, "/projects/" + p.slug)) })],
    ["PUT", /^\/projects\/([^/]+)\/(logo|banner)$/, (m, body, path) => {
      const p = project(m[1], path);
      if (!IMAGE_TYPES.includes(body.type)) fail(400, "invalid", "not PNG, JPEG or WebP", path, { fields: { body: "unsupported_type" } });
      if (body.size > IMAGE_MAX) fail(400, "invalid", "larger than 1 MiB", path, { fields: { body: "too_large" } });
      const key = m[1] + "/" + m[2];
      if (p[m[2]] && p[m[2]].source === "forge") forgeImages[key] = p[m[2]];
      if (uploaded[key] && window.URL && URL.revokeObjectURL) URL.revokeObjectURL(uploaded[key]);
      uploaded[key] = window.URL && URL.createObjectURL ? URL.createObjectURL(body.blob) : "uploaded-" + key;
      imageSerial += 1;
      p[m[2]] = { available: true, source: "uploaded", etag: "\"up" + imageSerial + "\"" };
      return { [m[2]]: p[m[2]] };
    }],
    ["PUT", /^\/me\/avatar$/, avatarRoute(() => me().member.id)],
    ["DELETE", /^\/me\/avatar$/, avatarRoute(() => me().member.id)],
    ["PUT", /^\/agents\/([^/]+)\/avatar$/, avatarRoute(ownAgent)],
    ["DELETE", /^\/agents\/([^/]+)\/avatar$/, avatarRoute(ownAgent)],
    ["DELETE", /^\/projects\/([^/]+)\/(logo|banner)$/, (m, body, path) => {
      const p = project(m[1], path);
      const key = m[1] + "/" + m[2];
      delete uploaded[key];
      // The forge's image applies again, where the fixture had one.
      const forge = forgeImages[key] || null;
      p[m[2]] = forge ? Object.assign({}, forge) : { available: false, source: null };
      return { [m[2]]: p[m[2]] };
    }],
    ["PATCH", /^\/projects\/([^/]+)$/, (m, body, path) => {
      const p = project(m[1], path);
      // §6.25: a rename, by a human owner; the old full name an alias.
      if ("slug" in body && body.slug !== p.slug) {
        if (me().member.kind !== "human" || trustIn(m[1]) !== "owner") fail(403, "forbidden", "a project is renamed by a human owner", path, { reason: "humans_only" });
        const owner = p.full_name.split("/")[0];
        renameCheck(p, path, owner + "/" + body.slug);
        if (!SLUG.test(body.slug || "")) fail(400, "invalid", "not a slug", path, { fields: { slug: "string_pattern_mismatch" } });
        if (ROUTE_WORDS.includes(body.slug)) fail(400, "invalid", "a route word", path, { fields: { slug: "reserved" } });
        const taken = slugOfFull(owner + "/" + body.slug);
        if (taken && taken !== m[1]) fail(400, "invalid", "taken", path, { fields: { slug: "taken" } });
        renamed(p, owner + "/" + body.slug);
        p.slug = body.slug;
        // /me's entry keeps the fixture directory as its slug; it answers with the project's.
        const mine = me().projects.find((x) => x.slug === m[1]);
        if (mine) mine.full_name = p.full_name;
      }
      if ("state" in body) {
        if (!body.reason) fail(400, "invalid", "A state change needs a reason", path, { fields: { reason: "required" } });
        p.state = body.state;
        p.state_note = body.state_note || null;
        p.state_changed_at = nowIso();
      }
      if ("absence" in body) p.absence = body.absence;
      if (body.settings && "language" in body.settings) {
        if (me().member.kind !== "human" || !["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "human project:admin needed", path);
        if (!["en", "de"].includes(body.settings.language)) fail(400, "invalid", "unknown language", path);
        p.settings = Object.assign({}, p.settings, { language: body.settings.language });
      }

      // §6.1, §17.3: the ticker setting, sent whole, by a human with project:admin.
      if (body.settings && "ticker" in body.settings) {
        if (me().member.kind !== "human" || !["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "human project:admin needed", path);
        const t = body.settings.ticker;
        if (t !== null && (typeof t !== "object" || (t.contract_files || []).length > 10 || Object.keys(t.contract_implementers || {}).length > 200
          || Object.values(t.contract_implementers || {}).some((v) => !Array.isArray(v) || v.length > 20))) {
          fail(400, "invalid", "the request does not validate", path, { fields: { "settings.ticker": "invalid" } });
        }
        const next = Object.assign({}, p.settings);
        if (t === null) delete next.ticker; else next.ticker = t;
        p.settings = next;
      }

      if (body.settings && "onboarding" in body.settings) {
        if (!["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "project:admin needed", path);
        const value = body.settings.onboarding || { check_in_with: "coordinator" };
        if (value.briefing && [...value.briefing].length > BRIEFING_CHARS) fail(400, "invalid", "Briefing too long", path);
        const old = (p.settings || {}).onboarding || {};
        p.settings = Object.assign({}, p.settings, { onboarding: Object.assign({}, value, {
          version: (old.version || 0) + 1, by: me().member, updated_at: nowIso(),
        }) });
      }

      if ("repository" in body) {
        if (!["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "project:admin needed", path, { scope: "project:admin" });
        const url = body.repository ? String(body.repository.url || "").replace(/\/+$/, "") : null;
        if (url !== null && !/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/.test(url)) {
          fail(400, "invalid", "the request does not validate", path, { fields: { "repository.url": "not_a_configured_forge" } });
        }
        const same = p.repository && p.repository.url === url;
        // What the repository had, kept by its URL, comes back with it: the
        // export follows the repository, and a new one has not been read yet.
        if (!same && p.repository) earlierRepos[m[1] + " " + p.repository.url] = { repository: p.repository, export: p.keep_the_why_export };
        const back = url && !same ? earlierRepos[m[1] + " " + url] : null;
        p.repository = back ? back.repository
          : url ? { url, default_branch: same ? p.repository.default_branch : "main", forge: "github", probe_configured: same ? p.repository.probe_configured : false } : null;
        if (!same && "keep_the_why_export" in p) p.keep_the_why_export = back ? back.export : null;
        // The repository first set: the setup cards chosen at creation (§6.21).
        if (url && p.setup && p.setup.cards === null && !["accepted", "archived"].includes(p.state)) makeSetupCards(m[1], p.setup, me().member.id, url);
      }
      if ("policy" in body) {
        // A policy change needs a reason; fields merge into the policy (docs/api.md §6.1).
        if (!body.reason) fail(400, "invalid", "A policy change needs a reason", path, { fields: { reason: "required" } });
        if ("signing" in body.policy && !["optional", "required"].includes(body.policy.signing)) {
          fail(400, "invalid", "unknown signing value", path, { fields: { "policy.signing": "unknown" } });
        }
        if ("badge" in body.policy && !["off", "members", "agents_online"].includes(body.policy.badge)) {
          fail(400, "invalid", "unknown badge value", path, { fields: { "policy.badge": "unknown" } });
        }
        if ("keep_the_why" in body.policy) {
          if (!["required", "optional"].includes(body.policy.keep_the_why)) fail(400, "invalid", "unknown keep_the_why value", path, { fields: { "policy.keep_the_why": "unknown" } });
          if (body.policy.keep_the_why === "required" && (p.memory || {}).provider === "none") {
            fail(400, "invalid", "no memory provider", path, { fields: { "policy.keep_the_why": "no_memory_provider" } });
          }
        }
        if ("member_agents" in body.policy && !["on", "off"].includes(body.policy.member_agents)) {
          fail(400, "invalid", "unknown member_agents value", path, { fields: { "policy.member_agents": "unknown" } });
        }
        if ("member_agents_max" in body.policy && !(Number.isInteger(body.policy.member_agents_max) && body.policy.member_agents_max >= 0 && body.policy.member_agents_max <= 20)) {
          fail(400, "invalid", "member_agents_max is 0 to 20", path, { fields: { "policy.member_agents_max": "out_of_range" } });
        }
        p.policy = Object.assign({}, p.policy, body.policy);
      }
      return p;
    }],
    // The log in fixture mode: fixtures/<slug>/events.json, the project
    // messages there and the ones posted in this tab (§8.3, oldest first).
    ["GET", /^\/projects\/([^/]+)\/events$/, (m, body, path, query) => {
      project(m[1], path);
      const log = eventsOf(m[1]);
      const head = log.length ? log[log.length - 1].seq : 0;
      const after = query.get("after");
      if (after === "latest") return { items: [], cursor: head, server_time: nowIso(), superseded: false };
      const limit = Math.min(200, Number(query.get("limit") || 50));
      const items = log.filter((e) => e.seq > Number(after || 0) && readable(m[1], e)).slice(0, limit).map(served);
      return { items, cursor: items.length ? items[items.length - 1].seq : Math.max(head, Number(after || 0)), server_time: nowIso(), superseded: false };
    }],
    // §17.9: the ticker in its compact form, per reader, newest first, paged
    // by an opaque cursor bound to the filters; after= oldest first.
    ["GET", /^\/projects\/([^/]+)\/ticker$/, (m, body, path, query) => {
      project(m[1], path);
      const t = tickerOf(m[1]);
      const TYPES = ["merge", "contract", "decision", "deploy", "release", "note"];
      const types = query.get("type") ? query.get("type").split(",") : null;
      const errors = {};
      if (types && types.some((x) => !TYPES.includes(x))) errors.type = "invalid";
      if (query.get("for") !== null && !["me", "all"].includes(query.get("for"))) errors.for = "invalid";
      const limit = query.get("limit") === null ? 50 : Number(query.get("limit"));
      if (!Number.isInteger(limit) || limit < 1 || limit > 200) errors.limit = "invalid";
      const since = query.get("since");
      if (since !== null && (!/(Z|[+-]\d{2}:\d{2})$/.test(since) || Number.isNaN(Date.parse(since)))) errors.since = "invalid";
      if (Object.keys(errors).length) fail(400, "invalid", "invalid query", path, { fields: errors });
      const area = query.get("area");
      const under = (p) => area && (area === "/" || p === area || p.startsWith(area.endsWith("/") ? area : area + "/"));
      const filterKey = [query.get("for") || "all", query.get("type") || "", area || "", since || ""].join("|");
      let items = t.items.filter((e) => tickerReadable(e)).map((e) => tickerItem(m[1], e))
        .filter((x) => (!types || types.includes(x.type) || (types.includes("contract") && x.type === "merge" && x.contract))
          && (!area || x.areas.some(under) || x._paths.some(under))
          && (query.get("for") !== "me" || x.for_me)
          && (!since || Date.parse(x.at) >= Date.parse(since)));
      const clean = (x) => { const y = Object.assign({}, x); delete y._paths; return y; };
      const after = query.get("after");
      if (after !== null) {
        const page = items.filter((x) => x.seq > Number(after)).sort((a, b) => a.seq - b.seq).slice(0, limit);
        return { items: page.map(clean), next_cursor: null };
      }
      items.sort((a, b) => b.seq - a.seq);
      const cursor = query.get("cursor");
      if (cursor !== null) {
        // Opaque to the page: "<seq>~<the filters it was made for>".
        const at = cursor.indexOf("~");
        const seqOf = Number(cursor.slice(0, at));
        if (at < 1 || !Number.isInteger(seqOf) || cursor.slice(at + 1) !== filterKey) fail(400, "invalid", "a cursor for other filters", path, { fields: { cursor: "invalid" } });
        items = items.filter((x) => x.seq < seqOf);
      }
      const page = items.slice(0, limit);
      const next = items.length > limit ? page[page.length - 1].seq + "~" + filterKey : null;
      return { items: page.map(clean), next_cursor: next };
    }],
    // The hub's machine form (§4): here only what the views ask of it.
    // §16.6: the instance's counts — a seeded month, or ?stats=empty a fresh
    // instance; a window beyond the fixture's days reads zero days, with
    // reviews unknown before the hub kept history, as the hub answers.
    ["GET", /^\/admin\/statistics$/, (m, body, path, query) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path, { scope: "instance:admin" });
      const n = Number(query.get("days") || 30);
      if (!Number.isInteger(n) || n < 1 || n > 90) fail(400, "invalid", "days is 1–90", path, { fields: { days: "out_of_range" } });
      const base = fixtures()[params.get("stats") === "empty" ? "admin-statistics-empty.json" : "admin-statistics.json"];
      const since = base.coverage.reviews_since;
      const days = [];
      for (let i = 0; i < n; i += 1) {
        const date = new Date(Date.parse(base.days[0].date + "T00:00:00Z") - i * 86400000).toISOString().slice(0, 10);
        days.push(base.days[i] || { date, registrations: 0, new_instances: 0, humans_active: 0, agents_active: 0,
          cards_created: 0, cards_claimed: 0, cards_done: 0, reviews: since && date < since ? null : 0 });
      }
      return Object.assign({}, base, { window_days: n, days });
    }],
    // §16.7: the public landing page — fixtures/landing.json, off as on
    // every fresh instance; ?landing=on shows it, ?landing=fail fails; the admin's settings
    // checked as the hub checks them (hub/src/maity_hub/landing.py).
    ["GET", /^\/landing$/, (m, body, path) => {
      if (params.get("landing") === "fail") fail(503, "unavailable", "the hub is unavailable", path);
      const v = fixtures()["landing.json"];
      if (!(v.enabled || params.get("landing") === "on")) return { enabled: false };
      return { enabled: true, title: v.title, markdown: v.markdown, cta: v.cta, updated_at: v.updated_at };
    }],
    ["GET", /^\/admin\/settings\/landing$/, (m, body, path) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path, { scope: "instance:admin" });
      return fixtures()["landing.json"];
    }],
    ["PATCH", /^\/admin\/settings\/landing$/, (m, body, path) => {
      if (!me().member.instance_admin) fail(403, "forbidden", "instance:admin needed", path, { scope: "instance:admin" });
      const v = Object.assign({}, fixtures()["landing.json"]);
      const errors = {};
      const target = (t) => /^\/#\/[A-Za-z0-9._~%\/?=&-]*$/.test(t) || /^https:\/\/[^\s/@]+(\/[^\s]*)?$/.test(t);
      Object.entries(body).forEach(([k, x]) => {
        if (!["enabled", "title", "markdown", "cta"].includes(k)) errors[k] = "extra_forbidden";
        else if (k === "enabled") { if (typeof x === "boolean") v.enabled = x; else errors.enabled = "invalid"; }
        else if (x === null) v[k] = null;
        else if (k === "title") { if (typeof x === "string" && x.trim() && x.length <= 120) v.title = x.trim(); else errors.title = "invalid"; }
        else if (k === "markdown") {
          let fence = null, bad = null;
          String(x).replace(/\r\n?/g, "\n").split("\n").some((line, i) => {
            if (fence) { if (line.trim().startsWith(fence)) fence = null; return false; }
            const f = /^ {0,3}(`{3,}|~{3,})/.exec(line);
            if (f) { fence = f[1]; return false; }
            const links = [...line.matchAll(/\]\(([^)\s]*)\)/g)].map((y) => y[1]);
            if (/<\/?[A-Za-z][^>]*>/.test(line) || /!\[/.test(line) || links.some((t) => !target(t))) { bad = "line " + (i + 1); return true; }
            return false;
          });
          if (bad) errors.markdown = bad; else v.markdown = x;
        } else if (k === "cta") {
          if (!x.label || !String(x.label).trim()) errors.cta = "invalid";
          else if (!target(x.href || "")) errors["cta.href"] = "invalid";
          else v.cta = { label: String(x.label).trim(), href: x.href };
        }
      });
      if (!Object.keys(errors).length && v.enabled && !v.markdown) errors.markdown = "required";
      if (Object.keys(errors).length) fail(400, "invalid", "the request does not validate", path, { fields: errors });
      v.updated_at = nowIso(); v.updated_by = me().member.id;
      fixtures()["landing.json"] = v;
      return v;
    }],
    // §6.22: the members' swarm (fixtures/<slug>/swarm.json) and its public
    // reduction where policy.swarm_public is on: agents only, no ids, no
    // pictures, no card titles, no live_at, as_of to the minute.
    ["GET", /^\/projects\/([^/]+)\/swarm$/, (m, body, path, query) => {
      project(m[1], path);
      const n = Number(query.get("days") || 30);
      if (!Number.isInteger(n) || n < 1 || n > 90) fail(400, "invalid", "days is 1–90", path, { fields: { days: "out_of_range" } });
      const s = fixtures()[m[1] + "/swarm.json"] || { as_of: nowIso(), live: [], members: [], totals: { cards_done: 0, reviews_given: 0, prs_merged: 0, handovers: 0,
        claim_to_done_median_seconds: null, review_to_done_median_seconds: null, cards_done_per_day: [] }, coverage: { reviews_since: null } };
      return Object.assign({}, s, { window_days: n, live_at: nowIso(),
        // Oldest first, as swarm.py sends them: the window is the last n days.
        totals: Object.assign({}, s.totals, { cards_done_per_day: (s.totals.cards_done_per_day || []).slice(-n) }) });
    }],
    // §6.25: /swarm/{owner}/{slug}; the old /swarm/{slug} redirects by the
    // frozen legacy_slug (followed here), answering as an unserved page else.
    ["GET", /^\/swarm\/([^/]+)(?:\/([^/]+))?$/, (m, body, path, query) => {
      const slug = m[2] ? slugOfFull(decodeURIComponent(m[1]) + "/" + decodeURIComponent(m[2]))
        : fixtureSlugs().find((x) => (fixtures()[x + "/project.json"] || {}).legacy_slug === decodeURIComponent(m[1]));
      const p = slug && fixtures()[slug + "/project.json"];
      const s = slug && fixtures()[slug + "/swarm.json"];
      if (!p || !s || (p.policy || {}).swarm_public !== "on" || ["accepted", "archived"].includes(p.state)) fail(404, "not_found", "Not found", path);
      const agents = (list) => list.filter((x) => x.kind === "agent");
      const sum = (rows, k) => rows.reduce((a, r) => a + (r[k] || 0), 0);
      const rows = agents(s.members).map((r) => ({ handle: r.handle, name: r.name, cards_done: r.cards_done, reviews_given: r.reviews_given,
        prs_merged: r.prs_merged, handovers: r.handovers, claim_to_done_median_seconds: r.claim_to_done_median_seconds, review_to_done_median_seconds: r.review_to_done_median_seconds }));
      return { as_of: s.as_of.slice(0, 16) + ":00Z", window_days: Number(query.get("days") || 30),
        live: agents(s.live).map((x) => ({ handle: x.handle, name: x.name, display_name: x.display_name, online: x.online, instances_online: x.instances_online, holding_count: (x.holding || []).length })),
        members: rows,
        totals: { cards_done: sum(rows, "cards_done"), reviews_given: sum(rows, "reviews_given"), prs_merged: sum(rows, "prs_merged"), handovers: sum(rows, "handovers"),
          claim_to_done_median_seconds: s.totals.claim_to_done_median_seconds, review_to_done_median_seconds: s.totals.review_to_done_median_seconds,
          cards_done_per_day: (s.totals.cards_done_per_day || []).slice(-Number(query.get("days") || 30)) },
        coverage: s.coverage };
    }],
    ["GET", /^\/openapi\.json$/, () => ({ openapi: "3.1.0", paths: {
      "/api/v1/admin/users": { get: {} },
      "/api/v1/admin/statistics": { get: {} },
      "/api/v1/admin/settings/landing": { get: {}, patch: {} },
      "/api/v1/landing": { get: {} },
      "/api/v1/admin/settings/mail": { get: {}, patch: {} },
      "/api/v1/admin/settings/mail/test": { post: {} },
      "/api/v1/health": { get: {} },
      "/api/v1/projects/{owner}/{slug}/ticker": { get: {}, post: {} },
      "/api/v1/projects/{owner}/{slug}/forge/webhook": { get: {} },
      "/api/v1/projects/{owner}/{slug}/forge/webhook/secret": { post: {}, delete: {} },
      "/api/v1/projects/{owner}/{slug}/ticker/subscription": { get: {}, patch: {} },
      "/api/v1/projects/{owner}/{slug}/conversations": { get: {}, post: {} },
      "/api/v1/me/conversations": { get: {} },
      "/api/v1/orgs": { get: {}, post: {} },
      "/api/v1/orgs/{org}": { get: {}, patch: {}, delete: {} },
      "/api/v1/orgs/{org}/avatar": { put: {}, delete: {} },
      "/api/v1/orgs/{org}/members": { get: {} },
      "/api/v1/orgs/{org}/members/{member_id}": { patch: {}, delete: {} },
      "/api/v1/orgs/{org}/members/invitations": { get: {}, post: {} },
      "/api/v1/orgs/{org}/members/invitations/{invitation_id}": { delete: {} },
      "/api/v1/me/export": { get: {} },
      "/api/v1/me/deletion": { post: {}, delete: {} },
      "/api/v1/me": { get: {}, patch: { requestBody: { content: { "application/json": { schema: { properties: { meat_proxy: {} } } } } } } },
      "/api/v1/projects/{owner}/{slug}/attachments": { get: {}, post: {} },
      "/api/v1/requests/{request_id}/answer": { post: {} },
      "/api/v1/auth/device-codes": { post: {} },
      "/api/v1/auth/methods": { get: {} },
      "/api/v1/me/preferences": { get: {}, put: {} },
      "/api/v1/requests/{request_id}/withdraw": { post: {} },
      "/api/v1/projects/{owner}/{slug}/swarm": { get: {} },
      "/api/v1/swarm/{owner}/{slug}": { get: {} },
      "/api/v1/projects/{owner}/{slug}/invitations": { get: {}, post: {} },
      "/api/v1/invitations/{token}": { get: {} },
      "/api/v1/auth/register": { post: {} },
      "/api/v1/projects": { get: {}, post: { requestBody: { content: { "application/json": { schema: { $ref: "#/components/schemas/ProjectCreate" } } } } } },
      "/api/v1/projects/{owner}/{slug}/tasks/{task_id}/contract": { get: {} },
      "/api/v1/projects/{owner}/{slug}/tasks/{task_id}/notes": { get: {}, post: {} },
      "/api/v1/projects/{owner}/{slug}/tasks/{task_id}/history": { get: {} },
      "/api/v1/projects/{owner}/{slug}/placements": { get: {}, post: {} },
    },
    components: { schemas: { ProjectCreate: { properties: {
      slug: {}, name: {}, repository: {}, memory: {}, setup: {}, keep_the_why: {}, policy: {},
    } } } } })],
    // §17.6: a manual post by an owner or admin.
    ["POST", /^\/projects\/([^/]+)\/ticker$/, (m, body, path) => {
      project(m[1], path);
      if (!["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "ticker:post needed", path, { scope: "ticker:post" });
      const errors = {};
      const type = body.type;
      if (["merge", "decision"].includes(type)) errors.type = "not_for_type";
      else if (type === undefined) errors.type = "required";
      else if (!["note", "deploy", "release"].includes(type)) errors.type = "invalid";
      const text = typeof body.text === "string" ? body.text : "";
      if (!text) errors.text = "required";
      else if (Array.from(text).length > 280) errors.text = "invalid";
      const https = (u) => typeof u === "string" && /^https:\/\/[^\s]+$/i.test(u) && u.length <= 2048;
      if (body.url !== undefined && body.url !== null && !https(body.url)) errors.url = "invalid";
      const to = body.to === undefined ? "computed" : body.to;
      const members = file(m[1], "members.json", path).items;
      if (!(to === "computed" || to === "all" || (Array.isArray(to) && to.length >= 1 && to.length <= 20
        && to.every((x) => /^(role|trust):[a-z]+$/.test(x) || /^area:\S+$/.test(x) || (/^member:/.test(x) && members.some((mm) => "member:" + mm.id === x)))))) errors.to = "invalid";
      if ("areas" in body && type !== "note") errors.areas = "not_for_type";
      if (type === "note" && to === "computed" && !(Array.isArray(body.areas) && body.areas.length)) errors.areas = "required";
      if ("release_task_id" in body && type !== "release") errors.release_task_id = "not_for_type";
      let card = null;
      if (type === "release") {
        card = (file(m[1], "tasks.json", path).items || []).find((x) => x.id === body.release_task_id) || null;
        if (!body.release_task_id) errors.release_task_id = "required";
        else if (!card || card.status !== "done") errors.release_task_id = "not_done";
      }
      if ("deploy" in body && type !== "deploy") errors.deploy = "not_for_type";
      if (type === "deploy") {
        const d = body.deploy || {};
        if (!d.environment) errors["deploy.environment"] = "required";
        else if (d.environment.length > 64) errors["deploy.environment"] = "invalid";
        if (!(d.sha || d.version)) errors.deploy = "required";
        if (d.log_url && !https(d.log_url)) errors["deploy.log_url"] = "invalid";
      }
      if (Object.keys(errors).length) fail(400, "invalid", "invalid fields", path, { fields: errors });
      const t = tickerOf(m[1]);
      const version = card && card.release ? card.release.version : null;
      const key = type === "deploy" ? "deploy:" + body.deploy.environment + ":" + (body.deploy.sha || body.deploy.version)
        : type === "release" ? "release:" + version : null;
      const dup = key && t.items.find((e) => e.payload.dedupe_key === key);
      if (dup) fail(409, "ticker_duplicate", "already posted", path, { seq: dup.seq });
      const log = eventsOf(m[1]);
      const seq = nextLogSeq(log.concat(t.items));
      const meId = me().member.id;
      // Resolved at write time to members (§17.6); the poster is never woken by its own post.
      const owners = (paths) => paths.map((x) => areaOwner(members, x)).filter(Boolean).map((mm) => mm.id);
      const resolve = (x) => (x.startsWith("member:") ? [x.slice(7)] : x.startsWith("role:") ? members.filter((mm) => mm.role === x.slice(5)).map((mm) => mm.id)
        : x.startsWith("trust:") ? members.filter((mm) => mm.trust === x.slice(6)).map((mm) => mm.id)
        : owners([x.slice(5)]));
      const reached = [...new Set(to === "all" ? members.map((x) => x.id) : Array.isArray(to) ? to.flatMap(resolve)
        : type === "note" ? owners(body.areas) : type === "deploy" ? members.map((x) => x.id) : members.map((x) => x.id))].filter((id) => id !== meId);
      const why = to === "all" ? "posted_to_all" : Array.isArray(to) ? "addressed" : type === "note" ? null : type === "release" ? "all_members" : "addressed";
      const reasonOf = (id) => (why ? [why] : ["area_owner:" + body.areas.find((a) => { const o = areaOwner(members, a); return o && o.id === id; })]);
      const event = { seq, kind: "ticker", at: nowIso(), actor: { kind: "member", member_id: meId }, subject: null,
        audience: ["all"].concat(reached.map((id) => "member:" + id)), redacted: false,
        payload: { type, text, url: body.url || null, dedupe_key: key, origin: { via: "manual", delivery: null }, merge: null, paths: [], paths_total: 0, paths_truncated: false,
          areas: type === "note" ? body.areas || [] : [], contract: null, tasks: body.release_task_id ? [body.release_task_id] : [], request: null,
          release: type === "release" ? { task_id: body.release_task_id, version } : null, deploy: type === "deploy" ? body.deploy : null,
          reasons: reached.map((id) => ({ member_id: id, why: reasonOf(id), wake: true, muted: false })) } };
      t.items.push(event);
      log.push(event);
      return served(event);
    }],
    // §17.8: one's own subscription, changed by what it adds and removes.
    ["GET", /^\/projects\/([^/]+)\/ticker\/subscription$/, (m) => Object.assign({}, tickerOf(m[1]).subscription)],
    ["PATCH", /^\/projects\/([^/]+)\/ticker\/subscription$/, (m, body, path) => {
      const sub = tickerOf(m[1]).subscription;
      const TYPES = ["merge", "contract", "decision", "deploy", "release", "note"];
      const errors = {};
      ["follow", "mute"].forEach((list) => ["areas", "types"].forEach((kind) => {
        const add = ((body.add || {})[list] || {})[kind] || [];
        const rem = ((body.remove || {})[list] || {})[kind] || [];
        if (add.some((v) => rem.includes(v))) errors[list + "." + kind] = "invalid";
        if (kind === "types" && add.concat(rem).some((v) => !TYPES.includes(v))) errors[list + ".types"] = "invalid";
        if (kind === "areas" && add.some((v) => !/^(\/|[^/\s][^\s]*)$/.test(v))) errors[list + ".areas"] = "invalid";
        const after = sub[list][kind].filter((v) => !rem.includes(v)).concat(add.filter((v) => !sub[list][kind].includes(v)));
        if (kind === "areas" && after.length > 20) errors[list + ".areas"] = "too_many";
      }));
      if (Object.keys(errors).length) fail(400, "invalid", "invalid fields", path, { fields: errors });
      ["follow", "mute"].forEach((list) => ["areas", "types"].forEach((kind) => {
        const add = ((body.add || {})[list] || {})[kind] || [];
        const rem = ((body.remove || {})[list] || {})[kind] || [];
        sub[list][kind] = sub[list][kind].filter((v) => !rem.includes(v)).concat(add.filter((v) => !sub[list][kind].includes(v)));
      }));
      sub.updated_at = nowIso();
      return Object.assign({}, sub);
    }],
    // §8.4: a message. The fixture resolves mentions as §8.6 says (a word
    // boundary, members only, never in code, no group mentions) and keeps
    // nothing: there is no feed in fixture mode.
    ["POST", /^\/projects\/([^/]+)\/events$/, (m, body, path) => {
      project(m[1], path);
      const errors = {};
      if (body.kind !== "message") errors.kind = "unknown";
      if (!["interface_change", "blocker", "go_request", "review_result", "handover", "notice", "chat"].includes(body.type)) errors.type = "unknown";
      // A message with attachments may have an empty body (§8.7).
      if ((!body.body || !String(body.body).trim()) && !(body.attachments || []).length) errors.body = "missing";
      if ("mentions" in body) errors.mentions = "read_only";
      const members = file(m[1], "members.json", path).items;
      const roles = ["owner", "admin", "reviewer", "member", "proxy"];
      if (!(body.to === "all" || (/^role:/.test(body.to || "") && roles.includes(body.to.slice(5))) || members.some((x) => x.id === body.to))) errors.to = "not_a_member";
      // A chat names its conversation and goes to its two parties only (§8.4).
      if (body.type === "chat" && !body.conversation_id) errors.conversation_id = "missing";
      if (Object.keys(errors).length) fail(400, "invalid", "invalid fields", path, { fields: errors });
      const text = String(body.body);
      const code = M.mentionCode ? M.mentionCode(text) : [];
      const mentions = [];
      // §8.6: a short handle or a global name (owner/handle) as one
      // candidate; a human comes first; a short handle two agents share is
      // refused with the long forms it could mean.
      const re = /(^|[^A-Za-z0-9_.@/+-])@([a-z0-9-]*[a-z0-9](?:\/[a-z0-9-]*[a-z0-9])?)(?![A-Za-z0-9_])/g;
      const ambiguous = {};
      for (let x = re.exec(text); x; x = re.exec(text)) {
        const at = x.index + x[1].length;
        if (body.type === "chat" || code.some(([a, b]) => at >= a && at < b)) continue;
        const long = x[2].includes("/");
        let hits = members.filter((mm) => (long ? mm.name === x[2] : mm.handle === x[2]));
        if (!long && hits.length > 1) {
          const human = hits.filter((mm) => mm.kind === "human");
          if (human.length) hits = human;
          else { ambiguous[x[2]] = hits.map((mm) => mm.name).sort(); continue; }
        }
        if (hits.length !== 1 || ["all", "here", "everyone", "owner"].includes(x[2])) continue;
        mentions.push({ member_id: hits[0].id, handle: hits[0].handle, name: hits[0].name || null, instance: null, field: "body",
          offset: Array.from(text.slice(0, at)).length, length: Array.from(x[2]).length + 1 });
      }
      if (Object.keys(ambiguous).length) fail(400, "invalid", "a short handle is two agents here", path, { fields: { body: "ambiguous_mention" }, mentions: ambiguous });
      if (new Set(mentions.map((x) => x.member_id)).size > 10 || mentions.length > 50) fail(400, "invalid", "too many mentions", path, { fields: { body: "too_many_mentions" } });
      const log = eventsOf(m[1]);
      const seq = nextLogSeq(log);
      const files = bindAttachments(m[1], body.attachments, seq, path);
      const event = { seq, kind: "message", at: nowIso(), actor: { kind: "member", member_id: me().member.id }, subject: body.task_id ? { type: "task", id: body.task_id } : null,
        audience: [body.to === "all" ? "all" : /^(role|trust):/.test(body.to) ? body.to : "member:" + body.to], redacted: false,
        payload: { type: body.type, to: body.to, body: text, task_id: body.task_id || null, conversation_id: null, mentions, attachments: files } };
      // A chat lives in its conversation; a project message in the log.
      if (body.type !== "chat") log.push(event);
      return event;
    }],
    ["GET", /^\/projects\/([^/]+)\/requests$/, (m, body, path, query) => {
      const keep = statusFilter(query, "open");
      return { items: file(m[1], "requests.json", path).items.filter(keep), next_cursor: null };
    }],
    ["POST", /^\/projects\/([^/]+)\/requests\/([^/]+)\/answer$/, (m, body, path) => {
      const req = file(m[1], "requests.json", path).items.find((r) => r.id === m[2]);
      if (!req) fail(404, "not_found", "Not found", path);
      if (req.status !== "open") fail(409, "request_not_open", "Request is not open", path);
      if (body.reply_id && !req.replies.some((r) => r.id === body.reply_id)) {
        fail(400, "invalid", "Unknown reply", path, { fields: { reply_id: "unknown" } });
      }
      const at = nowIso();
      req.status = "answered";
      req.answered_at = at;
      req.answer = {
        reply_id: body.reply_id || null,
        text: body.text || null,
        talk: !!body.talk,
        by: me().member.id,
        on_behalf_of: null,
        at,
        conversation_id: body.talk ? req.asked_by.member_id : null,
      };
      return req;
    }],
    // §6.11 the overview: counts per column (closed ones after closed_after),
    // open requests as this caller would list them, the latest reports.
    ["GET", /^\/projects\/([^/]+)\/overview$/, (m, body, path, query) => {
      const after = query.get("closed_after");
      if (after !== null && Number.isNaN(Date.parse(after))) fail(400, "invalid", "closed_after is no time", path, { fields: { closed_after: "invalid" } });
      const limit = query.get("limit") === null ? 10 : Number(query.get("limit"));
      if (!Number.isInteger(limit) || limit < 1 || limit > 50) fail(400, "invalid", "limit is 1 to 50", path, { fields: { limit: "invalid" } });
      const cards = file(m[1], "tasks.json", path).items;
      const counts = { proposed: 0, open: 0, in_progress: 0, blocked: 0, review: 0, done: 0, cancelled: 0 };
      cards.forEach((t) => {
        const closed = t.status === "done" || t.status === "cancelled";
        if (closed && after && Date.parse(t.closed_at || t.updated_at) <= Date.parse(after)) return;
        if (t.status in counts) counts[t.status] += 1;
      });
      const meId = me().member.id;
      const own = mineIn(m[1]);
      const answers = ["owner", "admin"].includes(own.trust) || own.role === "proxy";
      const mine = (r) => r.to === meId || r.to === "role:" + own.role || r.to === "trust:" + own.trust;
      const open = openFor(m[1]).filter((r) => answers || mine(r) || (r.asked_by && r.asked_by.member_id === meId));
      const byPriority = { urgent: 0, high: 0, normal: 0, low: 0 };
      open.forEach((r) => { if (r.priority in byPriority) byPriority[r.priority] += 1; });
      // A removed reporter keeps its handle and name (§6.2's removed member view).
      const mlist = file(m[1], "members.json", path);
      const members = mlist.items.concat(mlist.removed || []);
      const who = (id) => { const x = members.find((mm) => mm.id === id); return { member_id: id, handle: x ? x.handle : id, display_name: x ? x.display_name : id, avatar_url: x ? x.avatar_url || null : null }; };
      const reports = cards.filter((t) => t.report && t.report.reported_at)
        .sort((a, b) => (a.report.reported_at < b.report.reported_at ? 1 : -1)).slice(0, limit)
        .map((t) => {
          const r = t.report;
          const code = r.code !== false;
          return { task: { id: t.id, title: t.title, status: t.status, kind: t.kind, label: t.label || null },
            reported_by: who(r.reported_by), reported_at: r.reported_at, code, verification: r.verification || null,
            pr: code && r.pr_status === "found" && r.pr ? { number: r.pr.number, url: r.pr.url } : null,
            pr_state: r.observed ? r.observed.pr_state || null : null, observed_at: r.observed ? r.observed.observed_at || null : null,
            // null until the probe has looked (§6.6), never "no mismatch".
            mismatch: r.observed ? !!r.mismatch : null };
        });
      return { server_time: nowIso(),
        board: { counts, closed_after: after },
        requests: { open: open.length, to_me: open.filter(mine).length, by_priority: byPriority,
          oldest_open_at: open.length ? open.map((r) => r.created_at).sort()[0] : null },
        reports };
    }],
    ["GET", /^\/projects\/([^/]+)\/tasks$/, (m, body, path, query) => {
      const keep = statusFilter(query, "all");
      let items = file(m[1], "tasks.json", path).items.filter(keep);
      const q = query.get("q");
      if (q !== null) {
        if (!q || [...q].length > 200) fail(400, "invalid", "search must be 1–200 characters", path);
        const norm = (value) => String(value || "").normalize("NFKC").toLowerCase();
        const needle = norm(q);
        items = items.map((card) => {
          const match = ["id", "title", "body"].filter((key) => norm(card[key]).includes(needle));
          if (card.report && norm(card.report.summary).includes(needle)) match.push("report");
          return { ...card, match };
        }).filter((card) => card.match.length);
      }
      return { items, next_cursor: null };
    }],
    // One card (§6), its notes (§6.16, fixtures/<slug>/task-notes.json) and
    // its history (§6.15, fixtures/<slug>/task-history.json), newest first.
    ["GET", /^\/projects\/([^/]+)\/tasks\/([^/]+)$/, (m, body, path) => {
      const card = file(m[1], "tasks.json", path).items.find((c) => c.id === m[2]);
      if (!card) fail(404, "not_found", "Not found", path);
      return card;
    }],
    ["GET", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/notes$/, (m, body, path, query) => {
      if (!file(m[1], "tasks.json", path).items.some((c) => c.id === m[2])) fail(404, "not_found", "Not found", path);
      const all = (fixtures()[m[1] + "/task-notes.json"] || {})[m[2]] || [];
      const states = (query.get("state") || "open").split(",");
      return { items: states.includes("all") ? all : all.filter((n) => states.includes(n.state)), next_cursor: null };
    }],
    ["POST", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/notes$/, (m, body, path) => {
      const card = file(m[1], "tasks.json", path).items.find((c) => c.id === m[2]);
      if (!card) fail(404, "not_found", "Not found", path);
      if (["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      const text = String(body.body || "");
      if (!text.trim()) fail(400, "invalid", "body: missing", path, { fields: { body: "missing" } });
      if (utf8Bytes(text) > 4096) fail(400, "invalid", "body: too_long", path, { fields: { body: "too_long" } });
      const data = fixtures();
      const key = m[1] + "/task-notes.json";
      if (!data[key]) data[key] = {};
      const list = data[key][m[2]] || (data[key][m[2]] = []);
      const who = me().member;
      const note = { id: "nte-f" + String(list.length + 1).padStart(3, "0"), task_id: m[2],
        author: { member_id: who.id, handle: who.handle, kind: who.kind }, body: text, mentions: [], state: "open", resolution: null, created_at: nowIso() };
      list.push(note);
      card.notes = { open: list.filter((n) => n.state === "open").length, total: list.length };
      return note;
    }],
    ["GET", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/history$/, (m, body, path) => {
      if (!file(m[1], "tasks.json", path).items.some((c) => c.id === m[2])) fail(404, "not_found", "Not found", path);
      return { items: (fixtures()[m[1] + "/task-history.json"] || {})[m[2]] || [], next_cursor: null };
    }],
    // Release edits (docs/api.md §6.7). Readiness stays as the fixture has
    // it: computing it is the hub's, never the page's.
    ["PATCH", /^\/projects\/([^/]+)\/tasks\/([^/]+)$/, (m, body, path) => {
      if (!body.release) return patchCard(m[1], m[2], body, path);
      const card = releaseCard(m[1], m[2], path);
      const rel = card.release;
      if (body.release && body.release.checklist) {
        const old = {};
        rel.checklist.forEach((i) => { old[i.id] = i; });
        // A counter, never max+1, as the hub keeps it: a removed id is not given out again.
        let next = rel.next_item || rel.checklist.reduce((n, i) => Math.max(n, Number(i.id.slice(4)) || 0), 0) + 1;
        rel.checklist = body.release.checklist.map((i) => {
          if (i.id) {
            if (!old[i.id]) fail(400, "invalid", "unknown checklist item", path, { fields: { "release.checklist": "unknown_item:" + i.id } });
            return Object.assign({}, old[i.id], { text: i.text });
          }
          const item = { id: "chk-" + next, text: i.text, done: false, by: null, at: null };
          next += 1;
          return item;
        });
        rel.next_item = next;
      }
      if (body.release && body.release.pull_requests_typed) {
        // One entry per number, the last one winning, sorted by number, as the hub stores them.
        const byNumber = new Map();
        body.release.pull_requests_typed.forEach((p) => byNumber.set(p.number, { number: p.number, state: p.state || null }));
        rel.pull_requests_typed = Array.from(byNumber.values()).sort((a, b) => a.number - b.number);
        const typed = new Set(rel.pull_requests_typed.map((p) => p.number));
        const kept = rel.pull_requests.filter((p) => p.source !== "typed" || typed.has(p.number));
        rel.pull_requests_typed.forEach((p) => {
          if (!kept.some((k) => k.number === p.number)) {
            kept.push({ number: p.number, url: null, title: null, task_id: null, state: p.state, checks: null,
              head_sha: null, merged_at: null, observed_at: null, source: "typed", found: null });
          }
        });
        rel.pull_requests = kept.sort((a, b) => a.number - b.number);
      }
      card.updated_at = nowIso();
      return card;
    }],
    // §6.8: the contract's section as the hub read it, from
    // fixtures/<slug>/contracts.json keyed "path#section"; an entry with
    // `error` answers that refusal, a place without an entry not_found_in_file.
    ["GET", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/contract$/, (m, body, path) => {
      const card = file(m[1], "tasks.json", path).items.find((x) => x.id === m[2]);
      if (!card) fail(404, "not_found", "no such card", path);
      if (card.kind !== "contract") fail(400, "invalid", "contracts only", path, { fields: { contract: "contracts_only" } });
      const where = card.contract.path || "docs/api.md";
      if (!card.contract.section) fail(404, "not_found", "the card names no section", path, { fields: { "contract.section": "unset" } });
      const entry = (fixtures()[m[1] + "/contracts.json"] || {})[where + "#" + card.contract.section];
      if (!entry) fail(404, "not_found", "no such heading", path, { fields: { "contract.section": "not_found_in_file" } });
      if (entry.error) fail(entry.error.status, entry.error.code, entry.error.message, path, entry.error.fields ? { fields: entry.error.fields } : {});
      return Object.assign({ path: where, section: card.contract.section, fetched_at: nowIso() }, entry);
    }],
    // §6.4: a new card. assigned_to needs tasks:admin; freeze and fixes-only need a reason.
    ["POST", /^\/projects\/([^/]+)\/tasks$/, (m, body, path) => {
      const proj = project(m[1], path);
      if (["accepted", "archived"].includes(proj.state)) fail(409, "project_closed", "the project is closed", path);
      const list = file(m[1], "tasks.json", path).items;
      const errors = {};
      if (!body.title || !String(body.title).trim()) errors.title = "missing";
      if (body.label && !["fix", "feature", "chore"].includes(body.label)) errors.label = "unknown";
      if (body.status && !["proposed", "open"].includes(body.status)) errors.status = "unknown";
      if (["freeze", "fixes-only"].includes(proj.state) && !(body.reason && body.reason.trim())) errors.reason = "missing";
      if (body.assigned_to) {
        if (!tasksAdmin(m[1])) fail(403, "forbidden", "assigning needs tasks:admin", path, { scope: "tasks:admin" });
        if (!file(m[1], "members.json", path).items.some((x) => x.id === body.assigned_to)) errors.assigned_to = "not_a_member";
      }
      [...(body.depends_on || []), ...(body.ships_with || [])].forEach((id) => { if (!list.some((t) => t.id === id)) errors.depends_on = "unknown"; });
      // A release is never one of the cards shipped together (§6.7).
      if ((body.ships_with || []).length && (body.kind === "release" || body.ships_with.some((id) => (list.find((t) => t.id === id) || {}).kind === "release"))) errors.ships_with = "release_card";
      if (Object.keys(errors).length) fail(400, "invalid", "invalid fields", path, { fields: errors });
      // Under policy.subtasks "proposed" a member's subtask without a status starts as proposed; an explicit open is refused.
      if (body.parent && !body.status && ((proj.policy || {}).subtasks || "proposed") === "proposed" && !subtaskAdmin(m[1], path)) body = Object.assign({}, body, { status: "proposed" });
      if (body.parent) subtaskEdges(m[1], list, { id: "(new)", kind: body.kind || "task", status: body.status || "open" },
        { parent: body.parent, status: body.status || "open", depends_on: body.depends_on || [] }, path, { parent: null, status: "proposed" });
      taskSerial += 1;
      const at = nowIso();
      const card = { id: "tsk-f" + String(taskSerial).padStart(3, "0"), kind: body.kind || "task", title: body.title.trim(), body: body.body || "",
        label: body.label || null, status: body.status || "open", area: body.area || null, created_by: me().member.id,
        assigned_to: body.assigned_to || null, claim: null, checkpoint: null, depends_on: body.depends_on || [], ships_with: body.ships_with || [],
        blocked_by_request: null, ktw_ref: null, report: null, release: null, contract: null, mentions: [], created_at: at, updated_at: at, closed_at: null,
        parent: body.parent || null, related: [], children: { open: 0, total: 0 } };
      // ships_with is symmetric: the hub mirrors it on the other card.
      card.ships_with.forEach((id) => { const o = list.find((t) => t.id === id); o.ships_with = [...new Set([...(o.ships_with || []), card.id])]; });
      list.unshift(card);
      if (card.parent) { const p = list.find((t) => t.id === card.parent); p.children = childrenOf(list, p.id); }
      return card;
    }],
    ["POST", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/assign$/, (m, body, path) => {
      if (!tasksAdmin(m[1])) fail(403, "forbidden", "assigning needs tasks:admin", path, { scope: "tasks:admin" });
      const card = file(m[1], "tasks.json", path).items.find((x) => x.id === m[2]);
      if (!card) fail(404, "not_found", "no such card", path);
      if (!file(m[1], "members.json", path).items.some((x) => x.id === body.assignee)) fail(400, "invalid", "not a member", path, { fields: { assignee: "not_a_member" } });
      if (card.claim && !card.claim.expired && card.claim.holder !== body.assignee) fail(409, "lease_active", "the claim's lease is live", path);
      card.assigned_to = body.assignee;
      if (card.claim && card.claim.expired) card.claim = Object.assign({}, card.claim, { holder: body.assignee, expired: false });
      card.updated_at = nowIso();
      return card;
    }],
    // §6.4 card order: the card placed within its status column, under the
    // project's lock; the mock gives the whole column fresh ranks, as the
    // hub may at any time.
    ["POST", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/move$/, (m, body, path) => {
      if (!tasksAdmin(m[1])) fail(403, "forbidden", "ordering needs tasks:admin", path, { scope: "tasks:admin" });
      if (["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      const all = file(m[1], "tasks.json", path).items;
      const card = all.find((x) => x.id === m[2]);
      if (!card) fail(404, "not_found", "no such card", path);
      const key = ["before", "after", "to"].filter((k) => k in body);
      if (key.length !== 1 || (key[0] === "to" && !["top", "bottom"].includes(body.to))) fail(400, "invalid", "one of before, after or to", path, { fields: { body: "invalid" } });
      const cmp = (x, y) => (x < y ? -1 : x > y ? 1 : 0);
      const order = (a, b) => (a.rank && b.rank ? cmp(a.rank, b.rank) || cmp(a.id, b.id) : a.rank || b.rank ? (a.rank ? -1 : 1)
        : cmp(a.created_at || "", b.created_at || "") || cmp(a.id, b.id));
      const column = all.filter((x) => x.status === card.status && x !== card).sort(order);
      let at = body.to === "top" ? 0 : column.length;
      if (key[0] !== "to") {
        const near = all.find((x) => x.id === body[key[0]]);
        if (!near) fail(404, "not_found", "no such card", path);
        if (near === card || near.status !== card.status) fail(400, "invalid", "not a neighbour in this column", path, { fields: { [key[0]]: "invalid" } });
        at = column.indexOf(near) + (key[0] === "after" ? 1 : 0);
      }
      column.splice(at, 0, card);
      column.forEach((x, i) => { x.rank = "r" + String((i + 1) * 16).padStart(6, "0"); });
      card.updated_at = nowIso();
      return card;
    }],
    ["POST", /^\/projects\/([^/]+)\/tasks\/([^/]+)\/checklist\/([^/]+)$/, (m, body, path) => {
      const card = releaseCard(m[1], m[2], path);
      const item = card.release.checklist.find((i) => i.id === m[3]);
      if (!item) fail(404, "not_found", "no such checklist item", path);
      Object.assign(item, body.done ? { done: true, by: me().member.id, at: nowIso() } : { done: false, by: null, at: null });
      return card;
    }],
    ["GET", /^\/projects\/([^/]+)\/keep-the-why$/, (m, body, path, query) => {
      if (!project(m[1], path).keep_the_why_export) {
        fail(409, "ktw_not_configured", "the project has no Keep the Why export", path);
      }
      let answer = JSON.parse(JSON.stringify(file(m[1], "keep-the-why.json", path)));
      if (fixtureKtw === "member_failed" && answer.members.length > 1) {
        const failed = answer.members[answer.members.length - 1];
        failed.error = { code: "ktw_unavailable", reason: "timeout" };
        answer.summary.failed = 1;
      }
      if (fixtureKtw === "unavailable") {
        fail(503, "ktw_unavailable", "the root .keep-the-why could not be read", path,
          { reason: "forge_unavailable", last: Object.assign(answer, { fresh: false }) });
      }
      if (query.has("member")) {
        const one = answer.members.find((x) => x.path === query.get("member"));
        if (!one) fail(404, "not_found", "no such family member", path);
        answer = Object.assign(answer, { members: [one], summary: one.summary,
          attention: answer.attention.filter((a) => a.member === one.path) });
      }
      answer.fresh = query.get("max_age") === "0" || answer.fresh;
      return answer;
    }],
    // §6.2: owner and a credentials summary for an admin, and for an
    // agent's owner on their own agents; never for anyone else.
    ["GET", /^\/projects\/([^/]+)\/members$/, (m, body, path) => {
      const list = file(m[1], "members.json", path);
      const admin = membersAdmin(m[1]);
      const creds = fixtures()[m[1] + "/credentials.json"] || {};
      const monthAgo = Date.now() - 30 * 86400000;
      return { next_cursor: null, items: list.items.map((x) => {
        if (!admin && x.owner_id !== me().member.id) return x;
        if (x.kind !== "agent") return Object.assign({}, x, { owner: null, credentials: null });
        const all = (creds[x.id] || { items: [] }).items;
        const active = all.filter((c) => !c.revoked_at);
        const used = active.filter((c) => c.last_used_at).sort((a, b) => (a.last_used_at < b.last_used_at ? 1 : -1))[0];
        return Object.assign({}, x, {
          owner: humanOf(x.owner_id),
          credentials: { active: active.length, never_resumed: active.filter((c) => !c.resumed_at).length,
            revoked_recent: all.filter((c) => c.revoked_at && Date.parse(c.revoked_at) >= monthAgo).length,
            last_used_at: used ? used.last_used_at : null, last_used_via: used ? used.last_used_via || null : null },
        });
      }) };
    }],
    // §6.2 as the hub does it: every field checked first, each bad one
    // named at once, then one write. A reports-to circle or self is `cycle`
    // (#118). An admin agent stays within §2.3 ᵃ.
    ["PATCH", /^\/projects\/([^/]+)\/members\/([^/]+)$/, (m, body, path) => {
      const who = caller(m[1], path);
      // §19.4: the agent's owner, and nobody else, gives it their preferences.
      if ("owner_preferences" in body) {
        const target = member(m[1], m[2], path);
        if (Object.keys(body).length !== 1 || typeof body.owner_preferences !== "boolean") fail(400, "invalid", "set owner_preferences on its own", path, { fields: { owner_preferences: "alone" } });
        if (target.kind !== "agent" || target.owner_id !== who.member.id) fail(403, "forbidden", "the profile's owner only", path, { reason: "not_the_owner" });
        target.owner_preferences = body.owner_preferences;
        return target;
      }
      // §6.18: the team's rulebook, by the human who owns the agent profile only.
      if ("team" in body) {
        const target = member(m[1], m[2], path);
        if (Object.keys(body).length !== 1) fail(400, "invalid", "set team on its own", path, { fields: { team: "alone" } });
        if (who.member.kind !== "human" || target.kind !== "agent" || target.owner_id !== who.member.id) fail(403, "forbidden", "the profile's owner only", path, { reason: "humans_only" });
        const next = Object.assign({ max_instances: 1, distribution: "free", lead_instance: null, wake: "all", review_within_team: false }, target.team || {}, body.team);
        const errors = {};
        if (!Number.isInteger(next.max_instances) || next.max_instances < 1 || next.max_instances > 16) errors["team.max_instances"] = "out_of_range";
        if (!["free", "lead", "round_robin"].includes(next.distribution)) errors["team.distribution"] = "unknown";
        if (!["all", "lead", "next_free"].includes(next.wake)) errors["team.wake"] = "unknown";
        if ((next.distribution === "lead" || next.wake === "lead") && !next.lead_instance) errors["team.lead_instance"] = "required";
        if (next.lead_instance && !(target.instances || []).some((i) => i.id === next.lead_instance && !i.revoked_at)) errors["team.lead_instance"] = "not_an_instance";
        if (Object.keys(errors).length) fail(400, "invalid", "the request does not validate", path, { fields: errors });
        target.team = Object.assign(next, { updated_by: { kind: "human", id: who.member.id, handle: who.member.handle }, updated_at: nowIso() });
        return target;
      }
      if (!who.admin) fail(403, "forbidden", "members:admin needed", path, { scope: "members:admin" });
      const target = member(m[1], m[2], path);
      agentLimits(who.member, target, body, path);
      const all = file(m[1], "members.json", path).items;
      const errors = {};
      if ("briefing" in body && body.briefing !== null && [...body.briefing].length > BRIEFING_CHARS) errors.briefing = "string_too_long";
      // Trust and role (§2.3, as hub/routes/members.py checks them).
      const newTrust = "trust" in body ? body.trust : target.trust;
      const newRole = "role" in body ? body.role : target.role;
      if ("trust" in body) {
        if (!["owner", "admin", "member", "guest"].includes(body.trust)) errors.trust = "unknown";
        else if (body.trust === "owner" && target.kind !== "human") errors.trust = "humans_only";
        else if (target.trust === "owner" && body.trust !== "owner" && all.filter((x) => x.trust === "owner").length === 1) errors.trust = "last_owner";
        else if (body.trust !== "owner" && (project(m[1], path).owner || {}).id === target.id) {
          fail(409, "namespace_owner", "the project's namespace owner stays an owner", path, { projects: [fullOf(m[1])] });
        }
      }
      if ("role" in body && !["coder", "reviewer", "tester", "designer", "writer", "ops", "proxy", "manager"].includes(body.role)) errors.role = "unknown";
      if (!errors.trust && !errors.role && ("trust" in body || "role" in body) && newRole === "proxy" && newTrust !== "admin") errors.role = "proxy_needs_admin";
      if (who.member.kind === "human" && trustIn(m[1]) !== "owner" && ("trust" in body || "role" in body)
        && ((["owner", "admin"].includes(newTrust) && newTrust !== target.trust) || (newRole === "proxy" && target.role !== "proxy") || (target.trust === "owner" && newTrust !== "owner"))) {
        fail(403, "forbidden", "only an owner grants trust owner or admin, or the role proxy", path, { reason: "owner_only" });
      }
      if ("reports_to" in body && body.reports_to !== null) {
        const boss = all.find((x) => x.id === body.reports_to);
        if (!boss) errors.reports_to = "not_a_member";
        else {
          const seen = new Set();
          for (let at = body.reports_to; at && !seen.has(at); at = (all.find((x) => x.id === at) || {}).reports_to) {
            if (at === target.id) { errors.reports_to = "cycle"; break; }
            seen.add(at);
          }
        }
      }
      if ("areas" in body) {
        if ((body.areas || []).length > 50) errors.areas = "too_long";
        else if ((body.areas || []).some((a) => !/^[A-Za-z0-9._/-]{1,255}$/.test(a) || a.startsWith("..") || ("/" + a + "/").includes("/../"))) errors.areas = "invalid_path";
      }
      if ("capabilities" in body) {
        if ((body.capabilities || []).length > 20) errors.capabilities = "too_long";
        else if ((body.capabilities || []).some((c) => c !== "tag")) errors.capabilities = "unknown";
      }
      if (Object.keys(errors).length) fail(400, "invalid", "invalid fields", path, { fields: errors });
      if (guarded(m[1], target)) {
        const consent = ("role" in body && body.role !== target.role) || ("trust" in body && body.trust !== target.trust)
          ? consentFor(who.member, "Change " + target.handle + " to " + [newTrust, newRole].join(" · "))
          : body.paused ? consentFor(who.member, "Pause " + target.handle) : null;
        if (consent) return consent;
      }
      if ("trust" in body) target.trust = body.trust;
      if ("role" in body) target.role = body.role;
      if ("reports_to" in body) target.reports_to = body.reports_to;
      if ("areas" in body) target.areas = [...new Set(body.areas)];
      if ("capabilities" in body) target.capabilities = [...new Set(body.capabilities)];
      if ("briefing" in body) {
        target.briefing = body.briefing || null;
        target.briefing_by = { kind: me().member.kind, id: me().member.id, handle: me().member.handle };
        target.briefing_version = (target.briefing_version || 1) + 1;
      }
      if ("paused" in body) {
        target.paused = body.paused ? { reason: body.paused.reason, since: nowIso(), by: me().member.id } : null;
        target.presence = target.paused ? "paused" : (target.session ? "online" : "offline");
      }
      return target;
    }],
    // §6.25: the namespace owner hands the project to another human owner, a
    // consent request to them; the fixture hub files it and answers 202.
    ["POST", /^\/projects\/([^/]+)\/transfer$/, (m, body, path) => {
      const p = project(m[1], path);
      if (me().member.kind !== "human") fail(403, "forbidden", "a project is transferred by a human", path, { reason: "humans_only" });
      if (!p.owner || p.owner.id !== me().member.id) fail(403, "forbidden", "only the namespace owner transfers the project", path);
      const to = file(m[1], "members.json", path).items.find((x) => x.id === body.to && x.kind === "human" && x.trust === "owner");
      if (body.to === me().member.id) fail(400, "invalid", "the project is here already", path, { fields: { to: "self" } });
      if (!to) fail(400, "invalid", "the receiver must be an owner", path, { fields: { to: "not_an_owner" } });
      renameCheck(p, path, to.handle + "/" + p.slug);
      const list = file(m[1], "requests.json", path).items;
      list.filter((r) => r.status === "open" && r.kind === "project_transfer").forEach((r) => { r.status = "withdrawn"; });
      const req = { id: localId("req"), kind: "project_transfer", class: "consent", status: "open", title: "Take over " + p.full_name + " as " + to.handle + "/" + p.slug,
        summary: me().member.handle + " asks you to become the namespace owner of " + p.full_name + ".", options: [], replies: [{ id: "go", label: "Go" }, { id: "no", label: "No" }],
        priority: "normal", to: to.id, asked_by: { member_id: me().member.id, display_name: me().member.display_name }, created_at: nowIso(), while_open: "wait" };
      list.push(req);
      return Object.assign({}, req);
    }],
    ["DELETE", /^\/projects\/([^/]+)\/members\/([^/]+)$/, (m, body, path) => {
      const who = caller(m[1], path);
      if (!who.admin) fail(403, "forbidden", "members:admin needed", path, { scope: "members:admin" });
      const list = file(m[1], "members.json", path);
      // A second DELETE answers 200 with the removed member as it is.
      list.removed = list.removed || [];
      const gone = list.removed.find((x) => x.id === m[2]);
      if (gone) return gone;
      if ((project(m[1], path).owner || {}).id === m[2]) {
        fail(409, "namespace_owner", "the project's namespace owner is not removed", path, { projects: [fullOf(m[1])] });
      }
      const target = member(m[1], m[2], path);
      agentLimits(who.member, target, null, path);
      const consent = consentFor(who.member, "Remove " + target.handle);
      if (consent) return consent;
      if (target.trust === "owner" && who.member.kind === "human" && trustIn(m[1]) !== "owner") {
        fail(403, "forbidden", "only an owner removes an owner", path, { reason: "owner_only" });
      }
      if (target.trust === "owner" && list.items.filter((x) => x.trust === "owner").length === 1) {
        fail(400, "invalid", "the last owner cannot be removed", path, { fields: { member: "last_owner" } });
      }
      // Its credentials revoked, its claims released (§6.2).
      const at = nowIso();
      ((fixtures()[m[1] + "/credentials.json"] || {})[target.id] || { items: [] }).items.forEach((c) => {
        if (!c.revoked_at) { c.revoked_at = at; c.revoked_by = me().member.id; c.revoked_reason = "member_removed"; c.session_id = null; }
      });
      file(m[1], "tasks.json", path).items.forEach((t) => { if (t.claim && t.claim.holder === target.id) t.claim = null; });
      list.items = list.items.filter((x) => x !== target);
      list.items.forEach((x) => { if (x.reports_to === target.id) x.reports_to = null; });
      const removed = Object.assign({}, target, { removed_at: at });
      list.removed.push(removed);
      return removed;
    }],
    ["GET", /^\/projects\/([^/]+)\/members\/([^/]+)\/credentials$/,
      (m, body, path) => keyed(m[1], "credentials.json", m[2], path)],
    ["POST", /^\/projects\/([^/]+)\/credentials\/([^/]+)\/revoke$/, (m, body, path) => {
      const all = file(m[1], "credentials.json", path);
      for (const id of Object.keys(all)) {
        const c = all[id].items.find((x) => x.id === m[2]);
        if (c) {
          if (!c.revoked_at) {
            c.revoked_at = nowIso();
            c.revoked_by = me().member.id;
            c.revoked_reason = body.reason || null;
            c.session_id = null;
          }
          return c;
        }
      }
      return fail(404, "not_found", "Not found", path);
    }],
    // A fixture join with expires_in_seconds expires that long after the
    // fixtures were first read, so an open one stays open.
    ["GET", /^\/projects\/([^/]+)\/joins$/, (m, body, path) => {
      const list = file(m[1], "joins.json", path);
      list.items.forEach((j) => {
        if ("expires_in_seconds" in j) {
          j.expires_at = new Date(Date.now() + j.expires_in_seconds * 1000).toISOString().replace(/\.\d+Z$/, "Z");
          delete j.expires_in_seconds;
        }
      });
      return list;
    }],
    // The join line is made up here and shown once, as the hub would.
    ["POST", /^\/projects\/([^/]+)\/joins$/, (m, body, path) => {
      // §3.1 "Bringing your own agent": a human with trust member, within the project's limits.
      if (!["owner", "admin"].includes(trustIn(m[1]))) {
        const pol = project(m[1], path).policy || {};
        if (me().member.kind !== "human" || pol.member_agents === "off") fail(403, "forbidden", "members:admin needed", path, { scope: "members:admin" });
        const limit = (field) => fail(403, "forbidden", "not within the limits of bringing your own agent", path, { reason: "member_join_limit", field });
        if (body.agent && body.agent.id && !fixtures()["agents.json"].items.some((a) => a.id === body.agent.id && a.owner_id === me().member.id)) limit("agent");
        if (body.trust && !["member", "guest"].includes(body.trust)) limit("trust");
        if (body.role && !["coder", "reviewer", "tester", "designer"].includes(body.role)) limit("role");
        if (body.reports_to && body.reports_to !== me().member.id) limit("reports_to");
        if ((body.areas || []).length) limit("areas");
        if ((body.capabilities || []).length) limit("capabilities");
        if (!body.new_instance && !body.replaces) {
          const mine = new Set(file(m[1], "members.json", path).items.filter((x) => x.kind === "agent" && x.owner_id === me().member.id && !x.removed_at).map((x) => x.id));
          file(m[1], "joins.json", path).items.filter((j) => j.created_by === me().member.id && !j.used_at && !j.revoked_at && !j.burned && Date.parse(j.expires_at) > Date.now() && !j.new_instance && !j.replaces)
            .forEach((j) => mine.add(j.agent_id));
          const max = pol.member_agents_max === undefined ? 3 : pol.member_agents_max;
          if (mine.size >= max) fail(403, "forbidden", "you hold as many agents here as the project allows", path, { reason: "member_agents_max", max });
        }
      }
      let agentId = body.agent && body.agent.id;
      if (!agentId) {
        if (!body.agent || !body.agent.handle) fail(400, "invalid", "agent needs an id or a handle", path, { fields: { agent: "required" } });
        agentId = localId("agt");
        fixtures()["agents.json"].items.push({
          id: agentId, handle: body.agent.handle, name: me().member.handle + "/" + body.agent.handle, display_name: body.agent.display_name || body.agent.handle,
          owner_id: me().member.id, git_identity: null, memberships: [], created_at: nowIso(),
        });
      }
      if (body.briefing && [...body.briefing].length > BRIEFING_CHARS) {
        fail(400, "invalid", "the briefing is longer than 16,384 characters", path, { fields: { briefing: "string_too_long" } });
      }
      // §3.1, §6.17: a member's join says which instance it makes, as
      // routes/joins.py checks it; a first join says neither.
      const member = file(m[1], "members.json", path).items.find((x) => x.id === agentId);
      if (!member && (body.new_instance != null || body.replaces != null)) {
        fail(400, "invalid", "a first join creates the first instance", path, { fields: { [body.replaces != null ? "replaces" : "new_instance"]: "not_a_member" } });
      }
      if (member) {
        // routes/joins.py: the membership's own fields first, then the instance.
        const differ = ["role", "reports_to", "areas", "capabilities", "briefing"].filter((k) => k in body && body[k] != null
          && JSON.stringify(body[k]) !== JSON.stringify(member[k] === undefined ? null : member[k]));
        if (differ.length) fail(400, "invalid", "the agent is a member; change its membership instead", path, { fields: Object.fromEntries(differ.map((k) => [k, "differs_from_membership"])) });
        const active = (member.instances || []).filter((i) => !i.revoked_at);
        if (body.new_instance && body.replaces != null) fail(400, "invalid", "new_instance or replaces, not both", path, { fields: { instance: "one_of" } });
        if (body.replaces != null) {
          if (!active.some((i) => i.id === body.replaces)) fail(400, "invalid", "replaces names no active instance", path, { fields: { replaces: "not_an_instance" } });
        } else if (!body.new_instance) {
          fail(400, "invalid", "the agent is a member: new_instance or replaces", path, { fields: { instance: "required" } });
        } else if (active.length >= ((member.team && member.team.max_instances) || 1)) {
          fail(409, "instance_quota", "the team has as many instances as its rulebook allows", path, { max: (member.team && member.team.max_instances) || 1 });
        }
      }
      const id = localId("join");
      const ttl = Math.min(body.ttl_seconds || 900, 3600);
      const expires = new Date(Date.now() + ttl * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
      const url = "https://maity.example/j/FIXTURE-" + id;
      file(m[1], "joins.json", path).items.unshift({
        id, agent_id: agentId, trust: body.trust || "member", role: body.role || "coder", created_by: me().member.id,
        created_at: nowIso(), expires_at: expires, used_at: null, burned: false, revoked_at: null,
        new_instance: !!body.new_instance, replaces: body.replaces || null, instance: null,
      });
      return {
        id, join_url: url, code: "FIXT-URE0-0000", paste_line: "maity join " + url + " --code FIXT-URE0-0000",
        agent_id: agentId, project: fullOf(m[1]), expires_at: expires,
      };
    }],
    ["DELETE", /^\/projects\/([^/]+)\/joins\/([^/]+)$/, (m, body, path) => {
      const j = file(m[1], "joins.json", path).items.find((x) => x.id === m[2]);
      if (!j) fail(404, "not_found", "Not found", path);
      if (!j.revoked_at) {
        // §3.1: only an open join is revoked; a revoked one answers as it is.
        const from = j.used_at ? "used" : j.burned ? "burned" : Date.parse(j.expires_at) <= Date.now() ? "expired" : null;
        if (from) fail(409, "invalid_transition", "the join is " + from, path, { from, to: "revoked" });
        j.revoked_at = nowIso();
      }
      return j;
    }],
    // §8.7 attachments: a raw upload, pending until a message names it.
    ["POST", /^\/projects\/([^/]+)\/attachments$/, (m, body, path, query) => {
      attachmentsOn(path);
      if (["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      const name = query.get("name");
      if (!name) fail(400, "invalid", "a name is required", path, { fields: { name: "required" } });
      if (body.size > ATTACHMENT_MAX) fail(413, "payload_too_large", "larger than 10 MiB", path);
      const list = attachmentsOf(m[1]);
      const mine = list.filter((a) => a.uploaded_by === me().member.id && a.message_seq === null && !a.deleted_at);
      if (mine.length >= 20 || mine.reduce((n, a) => n + a.size, 0) + body.size > 100 * 1024 * 1024) {
        fail(409, "attachment_quota", "too many pending uploads", path, { scope: "pending" });
      }
      const declared = String(body.type || "").toLowerCase().split(";")[0].trim().replace("image/jpg", "image/jpeg");
      const image = ["image/png", "image/jpeg", "image/webp", "image/gif"].includes(declared);
      const at = nowIso();
      // Monotonic, never reused after a deletion (ids are opaque, §1.1).
      let id;
      do id = "att-" + String(++uploadSerial).padStart(4, "0"); while (list.some((x) => x.id === id));
      const att = {
        id,
        name: image && declared === "image/gif" ? name.replace(/\.gif$/i, "") + ".png" : name,
        size: body.size, type: image ? (declared === "image/gif" ? "image/png" : declared) : (/^[a-z0-9.+-]+\/[a-z0-9.+-]+$/.test(declared) ? declared : "application/octet-stream"),
        kind: image ? "image" : "file", sha256: "fixture", width: image ? 640 : null, height: image ? 480 : null,
        uploaded_by: me().member.id, uploaded_at: at, expires_at: new Date(Date.now() + 86400000).toISOString().replace(/\.\d{3}Z$/, "Z"),
        message_seq: null, deleted_at: null, deleted_by: null, deleted_reason: null,
      };
      list.push(att);
      try {
        if (window.URL && URL.createObjectURL && body.blob) attachmentBlobs[m[1] + "/" + att.id] = URL.createObjectURL(body.blob);
      } catch (ignored) {
        // Not a Blob (a test's stand-in): the file has no URL in this tab.
      }
      return att;
    }],
    ["GET", /^\/projects\/([^/]+)\/attachments$/, (m, body, path, query) => {
      attachmentsOn(path);
      const admin = ["owner", "admin"].includes(trustIn(m[1]));
      const pending = attachmentsOf(m[1]).filter((a) => a.message_seq === null && !a.deleted_at
        && (a.uploaded_by === me().member.id || admin) && (!query.get("uploaded_by") || a.uploaded_by === query.get("uploaded_by")));
      return { items: pending.map((a) => (a.uploaded_by === me().member.id ? Object.assign({}, a) : hiddenUpload(a))), next_cursor: null };
    }],
    ["GET", /^\/projects\/([^/]+)\/attachments\/([^/]+)$/, (m, body, path) => { attachmentsOn(path); return Object.assign({}, attachmentOf(m[1], m[2], path)); }],
    ["DELETE", /^\/projects\/([^/]+)\/attachments\/([^/]+)$/, (m, body, path) => {
      attachmentsOn(path);
      const a = attachmentOf(m[1], m[2], path);
      const meId = me().member.id;
      const admin = ["owner", "admin"].includes(trustIn(m[1]));
      if (a.deleted_at) return Object.assign({}, a);
      if (a.message_seq === null) {
        if (a.uploaded_by !== meId && !admin) fail(404, "not_found", "Not found", path);
        const list = attachmentsOf(m[1]);
        list.splice(list.indexOf(a), 1);
        return a.uploaded_by === meId ? Object.assign({}, a) : hiddenUpload(a);
      }
      // Of a message: its uploader; in a chat a human in it now; in a project message an admin.
      const where = messageOfSeq(m[1], a.message_seq);
      let allowed = a.uploaded_by === meId;
      if (!allowed && where && where.group) {
        const item = groupItem(m[1], where.group, path);
        if (!item) fail(404, "not_found", "Not found", path);
        if (item.access !== "participant") fail(403, "forbidden", "not a participant", path, { reason: "not_a_participant" });
        allowed = true;
      } else if (!allowed && where && where.direct) {
        const agent = file(m[1], "members.json", path).items.find((x) => x.id === where.direct);
        allowed = !!agent && agent.owner_id === meId;
      } else if (!allowed) {
        allowed = admin;
      }
      if (!allowed) fail(403, "forbidden", "members:admin needed", path, { scope: "members:admin" });
      Object.assign(a, { deleted_at: nowIso(), deleted_by: meId, deleted_reason: "deleted" });
      delete attachmentBlobs[m[1] + "/" + a.id];
      // A project message's file: the log says so to the message's audience (§8.2).
      const log = eventsOf(m[1]);
      const owner = log.find((e) => e.seq === a.message_seq);
      if (owner) {
        log.push({ seq: nextLogSeq(log), kind: "attachment_deleted", at: nowIso(), actor: { kind: "member", member_id: meId }, subject: null,
          audience: owner.audience.slice(), redacted: false, payload: { attachment_id: a.id, message_seq: a.message_seq, reason: "deleted", by: meId } });
      }
      return Object.assign({}, a);
    }],
    // §17.4: the forge webhook's state and its secret, a human with project:admin only; the secret answered once.
    ["GET", /^\/projects\/([^/]+)\/forge\/webhook$/, (m, body, path) => {
      if (me().member.kind !== "human" || !["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "human project:admin needed", path);
      const w = webhooks[m[1]] || {};
      return { configured: !!w.secret, url: hubOrigin() + "/api/v1/projects/" + projectPath(fullOf(m[1])) + "/forge/webhook", created_at: w.created_at || null,
        rotated_at: w.rotated_at || null, last_delivery_at: w.last_delivery_at || null, last_result: w.last_result || null };
    }],
    ["POST", /^\/projects\/([^/]+)\/forge\/webhook\/secret$/, (m, body, path) => {
      if (me().member.kind !== "human" || !["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "human project:admin needed", path);
      const w = webhooks[m[1]] || {};
      const secret = "whsec_" + Array.from({ length: 32 }, (_, i) => "abcdefghjkmnpqrstuvwxyz23456789"[(i * 7 + Date.now()) % 31]).join("");
      webhooks[m[1]] = Object.assign({}, w, { secret, created_at: w.created_at || nowIso(), rotated_at: w.secret ? nowIso() : null });
      return { secret, url: hubOrigin() + "/api/v1/projects/" + projectPath(fullOf(m[1])) + "/forge/webhook" };
    }],
    ["DELETE", /^\/projects\/([^/]+)\/forge\/webhook\/secret$/, (m, body, path) => {
      if (me().member.kind !== "human" || !["owner", "admin"].includes(trustIn(m[1]))) fail(403, "forbidden", "human project:admin needed", path);
      webhooks[m[1]] = {};
      return null;
    }],
    // §9.3: the direct conversations and the group chats, newest first; with
    // observed=true also the group chats read along as an agent's owner.
    ["GET", /^\/projects\/([^/]+)\/conversations$/, (m, body, path, query) => conversationList(m, path, query)],
    // §9.3 across projects: every project the human is a member of, one list,
    // newest activity first, then the project's full name, then the id; with
    // the project on each item and the unread totals over all of them.
    ["GET", /^\/me\/conversations$/, (m, body, path, query) => {
      const at = (c) => c.last_message_at || c.created_at || c.joined_at || "";
      const items = me().projects.flatMap((p) => conversationList([null, p.slug], path, query).items.map((c) => Object.assign({}, c, {
        project: { owner: p.full_name.split("/")[0], slug: p.slug, full_name: p.full_name, name: p.name } })));
      items.sort((a, b) => (at(b) > at(a) ? 1 : at(b) < at(a) ? -1 : 0)
        || a.project.full_name.localeCompare(b.project.full_name) || a.id.localeCompare(b.id));
      return { items, next_cursor: null,
        totals: { unread: items.reduce((n, c) => n + (c.unread || 0), 0), mentions_unread: items.reduce((n, c) => n + (c.mentions_unread || 0), 0) } };
    }],
    // §9.2 group chats.
    ["POST", /^\/projects\/([^/]+)\/conversations$/, (m, body, path) => {
      const chats = groupChats(m[1]);
      if (me().member.kind !== "human") fail(403, "forbidden", "humans only", path, { reason: "humans_only" });
      if (["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      const members = file(m[1], "members.json", path).items;
      const ids = [...new Set([me().member.id].concat(body.participants || []))];
      if (ids.some((id) => !members.some((x) => x.id === id))) fail(400, "invalid", "not a member", path, { fields: { participants: "not_a_member" } });
      if (ids.length < 2) fail(400, "invalid", "too few", path, { fields: { participants: "too_few" } });
      if (ids.length > 12) fail(400, "invalid", "too many", path, { fields: { participants: "too_many" } });
      const others = ids.filter((id) => id !== me().member.id).map((id) => members.find((x) => x.id === id));
      if (others.length === 1 && others[0].kind === "agent" && others[0].owner_id === me().member.id) {
        fail(400, "invalid", "that is the direct conversation", path, { fields: { participants: "use_direct" } });
      }
      const at = nowIso();
      const id = "cnv-" + String(Object.keys(chats).length + 100).padStart(4, "0");
      chats[id] = { view: { id, kind: "group", title: body.title || null, created_by: me().member.id, created_at: at,
        participants: ids.map((mid) => participantOf(members.find((x) => x.id === mid), at, 0)), closed_at: null, closed_reason: null },
      items: [], read: {} };
      return groupItem(m[1], chats[id], path);
    }],
    ["GET", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)$/, (m, body, path) => {
      const item = groupItem(m[1], groupChat(m[1], m[2], path), path);
      if (!item) fail(404, "not_found", "Not found", path);
      return item;
    }],
    ["PATCH", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)$/, (m, body, path) => {
      const c = managed(m[1], m[2], path);
      c.view.title = body.title || null;
      return groupItem(m[1], c, path);
    }],
    ["POST", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)\/participants$/, (m, body, path) => {
      const c = managed(m[1], m[2], path);
      if (["accepted", "archived"].includes(project(m[1], path).state)) fail(409, "project_closed", "the project is closed", path);
      const who = file(m[1], "members.json", path).items.find((x) => x.id === body.member_id);
      if (!who) fail(400, "invalid", "not a member", path, { fields: { member_id: "not_a_member" } });
      if (!c.view.participants.some((x) => x.member_id === who.id)) {
        if (c.view.participants.length >= 12) fail(400, "invalid", "too many", path, { fields: { participants: "too_many" } });
        const last = c.items.length ? c.items[c.items.length - 1].seq : 0;
        c.view.participants.push(participantOf(who, nowIso(), last));
      }
      return groupItem(m[1], c, path);
    }],
    ["DELETE", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)\/participants\/([^/]+)$/, (m, body, path) => {
      const c = groupChat(m[1], m[2], path);
      const self = m[3] === me().member.id;
      if (!self) managed(m[1], m[2], path);
      else if (!c.view.participants.some((x) => x.member_id === me().member.id)) fail(404, "not_found", "Not found", path);
      const gone = c.view.participants.find((x) => x.member_id === m[3]);
      if (!gone) fail(404, "not_found", "no such participant", path);
      c.view.participants = c.view.participants.filter((x) => x !== gone);
      if (gone.kind === "human") c.former = (c.former || []).concat(gone.member_id);
      // The last human gone: the chat closes (§9.2).
      if (!c.view.participants.some((x) => x.kind === "human")) { c.view.closed_at = nowIso(); c.view.closed_reason = "no_human"; }
      return { conversation_id: m[2], member_id: m[3], joined_at: gone.joined_at, left_at: nowIso(), by: me().member.id, reason: self ? "left" : "removed" };
    }],
    ["GET", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)\/messages$/, (m, body, path, query) => {
      const c = groupChat(m[1], m[2], path);
      const item = groupItem(m[1], c, path);
      if (!item) fail(404, "not_found", "Not found", path);
      if (query.get("after") !== null && query.get("before") !== null) fail(400, "invalid", "after or before", path, { fields: { before: "invalid" } });
      const limit = Math.min(200, Number(query.get("limit") || 50));
      const win = windowOf(c, me().member.id);
      let items;
      if (query.get("before") !== null) {
        const older = c.items.filter((x) => x.seq < Number(query.get("before")));
        items = older.slice(-limit);
      } else {
        items = win.filter((x) => x.seq > Number(query.get("after") || 0)).slice(0, limit);
        if (item.access === "participant" && items.length) c.read[me().member.id] = Math.max(c.read[me().member.id] || 0, items[items.length - 1].seq);
      }
      // earlier: the seq to pass as before; for a window with nothing in it
      // yet, everything said so far lies before it.
      const first = items.length ? items[0].seq : (win.length ? win[0].seq : (c.items.length ? c.items[c.items.length - 1].seq + 1 : null));
      const earlier = first !== null && c.items.some((x) => x.seq < first) ? first : null;
      // An admin's reason is shown to it and the chat's former humans only (§8.5).
      const shown = (x) => {
        const v = messageView(x);
        if (v.redaction && v.redaction.admin_reason) {
          const r = Object.assign({}, v.redaction);
          delete r.admin_reason;
          if (item.access === "observer" || me().member.kind !== "human") r.reason = null;
          v.redaction = r;
        }
        return v;
      };
      return { items: items.map(shown), cursor: items.length ? items[items.length - 1].seq : null, earlier };
    }],
    ["POST", /^\/projects\/([^/]+)\/conversations\/(cnv-[^/]+)\/messages$/, (m, body, path) => {
      const c = groupChat(m[1], m[2], path);
      const item = groupItem(m[1], c, path);
      if (!item) fail(404, "not_found", "Not found", path);
      if (item.access === "observer") fail(403, "forbidden", "an observer does not post", path, { reason: "observer" });
      if (c.view.closed_at) fail(409, "conversation_closed", "the chat is closed", path);
      // One sequence for the project's messages, as the event log has it.
      const last = Math.max(5000, ...Object.values(groupChats(m[1])).flatMap((x) => x.items.map((y) => y.seq)),
        ...Object.values(file(m[1], "conversations.json", path)).flatMap((x) => x.items.map((y) => y.seq)));
      if ((!body.body || !String(body.body).trim()) && !(body.attachments || []).length) fail(400, "invalid", "the message is empty", path, { fields: { body: "missing" } });
      const msg = { id: "evt-" + (last + 1), seq: last + 1, conversation_id: m[2], from: me().member.id, to: m[2], body: body.body || "", sent_at: nowIso(), mentions: [],
        attachments: bindAttachments(m[1], body.attachments, last + 1, path) };
      c.items.push(msg);
      c.read[me().member.id] = msg.seq;
      return msg;
    }],
    // §8.5: a chat message redacted by a human in the room, the direct chat's
    // human party with events:admin, or blind in a closed group chat.
    ["POST", /^\/projects\/([^/]+)\/events\/(\d+)\/redact$/, (m, body, path) => {
      const seq = Number(m[2]);
      const chats = groupChats(m[1]);
      const meId = me().member.id;
      const admin = ["owner", "admin"].includes(trustIn(m[1]));
      let msg = null;
      let chat = null;
      let direct = null;
      Object.values(chats).forEach((c) => { const x = c.items.find((y) => y.seq === seq); if (x) { msg = x; chat = c; } });
      if (!msg) Object.entries(file(m[1], "conversations.json", path)).forEach(([agentId, c]) => { const x = c.items.find((y) => y.seq === seq); if (x) { msg = x; direct = agentId; } });
      // A project message (§8.4): events:admin, owner or admin; the payload becomes the tombstone.
      const logged = !msg && body.expect === undefined ? eventsOf(m[1]).find((e) => e.seq === seq) : null;
      if (logged) {
        if (!admin) fail(403, "forbidden", "events:admin needed", path, { scope: "events:admin" });
        if (typeof body.reason !== "string" || !body.reason.trim()) fail(400, "invalid", "a reason is required", path, { fields: { reason: "missing" } });
        attachmentsOf(m[1]).filter((a) => a.message_seq === seq && !a.deleted_at)
          .forEach((a) => Object.assign(a, { deleted_at: nowIso(), deleted_by: meId, deleted_reason: "redacted" }));
        Object.assign(logged, { redacted: true, payload: { redacted: true, reason: body.reason, by: meId, at: nowIso() } });
        const log = eventsOf(m[1]);
        log.push({ seq: nextLogSeq(log), kind: "event_redacted", at: nowIso(), actor: { kind: "member", member_id: meId }, subject: null,
          audience: ["trust:owner", "trust:admin"], redacted: false, payload: { seq, reason: body.reason } });
        return served(logged);
      }
      // expect (#206): only a closed group chat's message, else nothing changes.
      if (body.expect !== undefined && !(chat && chat.view.closed_at)) fail(400, "invalid", "not a closed group chat's message", path, { fields: { expect: "mismatch" } });
      if (!msg) fail(404, "not_found", "Not found", path);
      if (typeof body.reason !== "string" || !body.reason.trim()) fail(400, "invalid", "a reason is required", path, { fields: { reason: "missing" } });
      const stamp = (extra) => {
        // A redacted message takes its files with it (§8.7, deleted_reason redacted).
        attachmentsOf(m[1]).filter((a) => a.message_seq === seq && !a.deleted_at)
          .forEach((a) => { Object.assign(a, { deleted_at: nowIso(), deleted_by: meId, deleted_reason: "redacted" }); delete attachmentBlobs[m[1] + "/" + a.id]; });
        return Object.assign(msg, { body: null, mentions: [], redacted: true, redaction: Object.assign({ at: nowIso(), by: meId, reason: body.reason }, extra) });
      };
      const event = () => ({ seq, kind: "message", redacted: true, payload: { redacted: true, reason: body.reason, by: meId, at: nowIso() } });
      if (chat) {
        const item = groupItem(m[1], chat, path);
        const former = (chat.former || []).includes(meId);
        if (chat.view.closed_at && former) { stamp(); return event(); }
        // The blind removal: an admin who cannot read the chat learns only
        // that it is removed; its reason is shown to it and the former humans.
        if (chat.view.closed_at && admin && (!item || item.access !== "participant")) { stamp({ admin_reason: true }); return { seq, redacted: true }; }
        if (!item) fail(404, "not_found", "Not found", path);
        if (item.access !== "participant") fail(403, "forbidden", "not a participant", path, { reason: "observer" });
        stamp();
        return event();
      }
      // A direct chat: its human party, holding events:admin (§8.5).
      const agent = file(m[1], "members.json", path).items.find((x) => x.id === direct);
      if (!agent || agent.owner_id !== meId) fail(404, "not_found", "Not found", path);
      if (!admin) fail(403, "forbidden", "events:admin needed", path, { scope: "events:admin" });
      stamp();
      return event();
    }],
    // §9.1: after= reads forward and marks what it returns read; before=
    // the limit messages below it, marking nothing; earlier the page's
    // lowest seq while older ones exist.
    ["GET", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/, (m, body, path, query) => {
      const conv = keyed(m[1], "conversations.json", m[2], path);
      if (query.get("after") !== null && query.get("before") !== null) fail(400, "invalid", "after or before", path, { fields: { before: "invalid" } });
      const limit = Math.min(200, Number(query.get("limit") || 200));
      let items;
      if (query.get("before") !== null) {
        items = conv.items.filter((x) => x.seq < Number(query.get("before"))).slice(-limit);
      } else {
        const after = Number(query.get("after") || 0);
        items = conv.items.filter((x) => x.seq > after).slice(0, limit);
        items.forEach((x) => { x.seen_by_human = true; });
      }
      const earlier = items.length && conv.items.some((x) => x.seq < items[0].seq) ? items[0].seq : null;
      return {
        items: items.map((x) => {
          const copy = messageView(x);
          delete copy.seen_by_human;
          return copy;
        }),
        cursor: query.get("before") !== null ? 0 : (items.length ? items[items.length - 1].seq : (conv.items.length ? conv.items[conv.items.length - 1].seq : null)),
        earlier,
      };
    }],
    ["POST", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/, (m, body, path) => {
      const conv = keyed(m[1], "conversations.json", m[2], path);
      const last = conv.items.length ? conv.items[conv.items.length - 1].seq : 5000;
      if ((!body.body || !String(body.body).trim()) && !(body.attachments || []).length) fail(400, "invalid", "the message is empty", path, { fields: { body: "missing" } });
      const msg = {
        id: "evt-" + (last + 1), seq: last + 1, conversation_id: m[2],
        from: me().member.id, to: m[2], body: body.body || "", sent_at: nowIso(), delivered_at: null,
        attachments: bindAttachments(m[1], body.attachments, last + 1, path),
      };
      conv.items.push(Object.assign({ seen_by_human: true }, msg));
      return msg;
    }],
  ];

  function fromFixtures(method, fullPath, body) {
    const q = fullPath.indexOf("?");
    const asked = q < 0 ? fullPath : fullPath.slice(0, q);
    const query = new URLSearchParams(q < 0 ? "" : fullPath.slice(q + 1));
    return loadFixtures().then(() => {
      let path = asked;
      // The hub serves its machine form and the landing page without a session.
      // Signed out, the fixture hub still answers what a visitor calls, and the
      // device codes, whose other side this one tab plays too.
      if (!fixtureSignedIn && !/^\/auth\/(session|login|logout|register|methods|device-login(\/complete)?|email-link|email-code|device-codes(\/.*)?)$/.test(path) && path !== "/landing" && path !== "/openapi.json" && !path.startsWith("/swarm/") && !path.startsWith("/invitations/")) {
        fail(401, "unauthenticated", "Not signed in", fullPath);
      }
      path = namespaced(path, fullPath);
      for (const [verb, pattern, handler] of routes) {
        if (verb !== method) continue;
        const match = pattern.exec(path);
        // Hand out copies, like a network answer would.
        if (match) return JSON.parse(JSON.stringify(handler(match, body || {}, fullPath, query)));
      }
      return fail(404, "not_found", "No fixture for " + method + " " + path, fullPath);
    });
  }

  // ---- API mode -----------------------------------------------------------

  // The CSRF token from GET /auth/session; the readable maity_csrf cookie
  // carries the same value and is preferred when present.
  let sessionCsrf = null;

  function csrfToken() {
    for (const part of document.cookie.split(";")) {
      const eq = part.indexOf("=");
      if (eq > 0 && part.slice(0, eq).trim() === "maity_csrf") {
        return decodeURIComponent(part.slice(eq + 1).trim());
      }
    }
    return sessionCsrf;
  }

  // signal: an AbortSignal that cancels the request (a held long-poll the
  // page no longer wants, js/notify.js).
  async function fromApi(method, path, body, raw, signal) {
    const init = {
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    if (signal) init.signal = signal;
    // Every POST, PATCH and DELETE of a cookie session carries the token;
    // without one the hub answers 403 csrf_mismatch.
    if (method !== "GET" && method !== "HEAD") {
      const token = csrfToken();
      if (token) init.headers["X-CSRF-Token"] = token;
    }
    if (raw) {
      // An image upload (§11.2): the raw bytes, typed, no JSON.
      init.headers["Content-Type"] = raw;
      init.body = body;
    } else if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(API_BASE + path, init);
    } catch (err) {
      if (err && err.name === "AbortError") throw new ApiError("Cancelled", 0, path, "aborted");
      throw new ApiError("The hub did not answer: " + err.message, 0, path);
    }
    // Maity-Server-Time on every answer (docs/api.md §1.2): how far this
    // browser's clock is off the hub's, for judging expiry as the hub does.
    const served = res.headers && res.headers.get ? Date.parse(res.headers.get("Maity-Server-Time") || "") : NaN;
    if (!Number.isNaN(served)) skew = served - Date.now();
    if (!res.ok) {
      let detail = res.statusText;
      let code = res.headers && res.headers.get ? res.headers.get("Maity-Error") : null;
      let details = {};
      try {
        const data = await res.json();
        if (data && data.error) {
          code = data.error.code || code;
          detail = data.error.message || data.error.code || detail;
          details = data.error.details || {};
        }
      } catch (ignored) {
        // Not JSON; the status text and the Maity-Error header are all there is.
      }
      if (code === "csrf_mismatch") detail += " (reload the page to get a fresh token)";
      throw new ApiError(detail || ("HTTP " + res.status), res.status, path, code, details);
    }
    // 204 has no body: a deletion, a removal, a withdrawal (§6.26 among them).
    if (res.status === 204) return null;
    return res.json();
  }

  let skew = 0;
  let sessionBlocked = false;
  const obsoleteSession = (path) => new ApiError("The session ended", 0, path, "aborted");

  function request(method, path, body, raw, signal) {
    const publicCall = PUBLIC_PATH.test(path);
    const epoch = M.sessionEpoch || 0;
    if (sessionBlocked && !publicCall) return Promise.reject(obsoleteSession(path));
    // In fixture mode an image travels with the Content-Type the page sniffed.
    const p = source === "fixtures"
      ? fromFixtures(method, path, raw ? { blob: body, type: raw, size: body.size } : body)
      : fromApi(method, path, body, raw, signal);
    if (path === "/auth/session") {
      return p.then((s) => {
        if (epoch !== (M.sessionEpoch || 0)) throw obsoleteSession(path);
        sessionCsrf = s.csrf_token || null;
        sessionBlocked = false;
        return s;
      });
    }
    // A 401 on a call that needs the session: it ended (expired, revoked,
    // ended elsewhere). The page is told once, in one place (js/app.js).
    if (!publicCall) {
      // Which session asked: a late 401 of an earlier one ends no later one.
      return p.then((answer) => {
        if (sessionBlocked || epoch !== (M.sessionEpoch || 0)) throw obsoleteSession(path);
        return answer;
      }, (err) => {
        if (err && err.status === 401 && M.onSessionEnded) M.onSessionEnded(path, epoch);
        throw err;
      });
    }
    return p;
  }
  // The calls a visitor without a session makes, where a 401 says nothing ended.
  // Signing in and out, registering and the session check answer 401 to a
  // visitor by design; every other /auth/* call is the session's own.
  // The path carries its query (the device-login wait, ?wait=0): a public
  // route ends at the path, whatever query follows.
  const PUBLIC_PATH = /^\/(auth\/(session|login|logout|register|methods|device-login(\/complete)?|email-link|email-code)|landing|openapi\.json|swarm\/[^?]*|invitations\/[^/?]+)(\?|$)/;

  // Every page of a list, following next_cursor (docs/api.md §1.4).
  async function getAll(path) {
    const sep = path.includes("?") ? "&" : "?";
    let page = await request("GET", path + sep + "limit=200");
    const items = page.items.slice();
    while (page.next_cursor) {
      page = await request("GET", path + sep + "limit=200&cursor=" + encodeURIComponent(page.next_cursor));
      items.push(...page.items);
    }
    return { items, next_cursor: null };
  }

  // What the hub serves, from its machine form (GET /openapi.json), read
  // once per page: a view offers a control only for a route the hub lists.
  // The hub lists its paths under its prefix (/api/v1/…); either form
  // counts, as in the CLI, and parameter names are not compared. A failed
  // read is not kept: the next ask reads again.
  let hubDoc = null;
  let hubPaths = null;
  const routeKey = (method, path) => method.toUpperCase() + " "
    + path.replace(/^\/api\/v1(?=\/)/, "").replace(/\{[^}]*\}/g, "{}");
  function machineForm() {
    if (!hubDoc) {
      hubDoc = M.api.get("/openapi.json");
      hubDoc.catch(() => { hubDoc = null; });
    }
    return hubDoc;
  }
  function hubRoutes() {
    if (!hubPaths) {
      hubPaths = machineForm().then((doc) => {
        const found = new Set();
        Object.entries((doc && doc.paths) || {}).forEach(([path, ops]) =>
          Object.keys(ops || {}).forEach((method) => found.add(routeKey(method, path))));
        return found;
      });
      hubPaths.catch(() => { hubPaths = null; });
    }
    return hubPaths;
  }

  // The fields the hub's machine form names for the JSON body of `method
  // path` (path as in docs/api.md), one $ref followed: what a form may
  // send to this hub. Rejects when the machine form cannot be read.
  function bodyFields(method, path) {
    return machineForm().then((doc) => {
      const paths = (doc && doc.paths) || {};
      const op = (paths["/api/v1" + path] || paths[path] || {})[method.toLowerCase()];
      const json = op && op.requestBody && op.requestBody.content && op.requestBody.content["application/json"];
      let schema = json && json.schema;
      if (schema && schema.$ref) schema = schema.$ref.split("/").slice(1).reduce((o, k) => (o ? o[k] : null), doc);
      return new Set(Object.keys((schema && schema.properties) || {}));
    });
  }

  // Whether the hub's machine form lists a route for this method and this
  // concrete path (its parameters matched as path segments); null when the
  // machine form cannot be read.
  const escapeRe = (t) => t.replace(/[.*+?^$()|[\]\\]/g, "\\$&");
  function routeListed(method, path) {
    const want = method.toUpperCase();
    const at = String(path).split("?")[0];
    return hubRoutes().then((found) => Array.from(found).some((key) => {
      const [m, template] = key.split(" ");
      return m === want && new RegExp("^" + template.split("{}").map(escapeRe).join("[^/]+") + "$").test(at);
    }), () => null);
  }

  // A route this hub does not serve: a 404 or 405 for a method and path its
  // machine form does not list. Where a view's feature needs one, that is a
  // fact of this hub, said quietly in its place (M.dom.notOnHub), never as
  // an error, and the view does not ask it again until the next navigation,
  // so no timer keeps knocking. A 404 on a route the hub lists is the
  // resource's (a project left, a card gone) and stays an error, as does an
  // answer when the machine form cannot be read, and any 5xx, network
  // failure, 401 or 403.
  const absentRoutes = new Set();
  const routeOf = (method, path) => method.toUpperCase() + " " + String(path).split("?")[0];

  M.api = {
    endSession: () => {
      sessionBlocked = true;
      sessionCsrf = null;
      M.sessionEpoch = (M.sessionEpoch || 0) + 1;
    },
    // Whether a 401 on this path says nothing about a session (above).
    isPublicPath: (path) => PUBLIC_PATH.test(path),
    notOnHub: (err) => !!err && (err.status === 404 || err.status === 405),
    // A promise: true when err says the route itself is missing (see above).
    missingRoute: (err, method, path) => (!!err && (err.status === 404 || err.status === 405)
      ? routeListed(method, path).then((yes) => yes === false) : Promise.resolve(false)),
    absent: {
      note: (method, path) => { absentRoutes.add(routeOf(method, path)); },
      has: (method, path) => absentRoutes.has(routeOf(method, path)),
      // On every navigation (js/app.js): a hub deployed meanwhile is asked again.
      clear: () => { absentRoutes.clear(); },
    },
    // Whether the hub serves `method path` (path as in docs/api.md, without
    // the prefix); rejects when its machine form cannot be read.
    hubHas: (method, path) => hubRoutes().then((found) => found.has(routeKey(method, path))),
    hubBody: bodyFields,
    // Reads the machine form again at the next ask (the smoke test's hubs).
    forgetRoutes: () => { hubDoc = null; hubPaths = null; absentRoutes.clear(); },
    // The hub's time as best known: this clock corrected by the last answer's.
    now: () => Date.now() + skew,
    source,
    ApiError,
    get: (path, opts) => request("GET", path, undefined, undefined, opts && opts.signal),
    getAll,
    post: (path, body) => request("POST", path, body || {}),
    put: (path, body) => request("PUT", path, body || {}),
    // PUT of an image as its raw bytes; type is the sniffed Content-Type.
    putImage: (path, blob, type) => request("PUT", path, blob, type),
    // POST of a file as its raw bytes (§8.7); type is its Content-Type.
    postRaw: (path, blob, type) => request("POST", path, blob, type),
    // The URL of an attachment's bytes (§8.7): the hub's own path, or in
    // fixture mode the object URL of the file chosen in this tab.
    // A project's path segments from its full name (§6.25): `<owner>/<slug>`,
    // each part encoded, the slash between them kept.
    projectPath,
    attachmentUrl: (full, id, download) => {
      if (source === "fixtures") return attachmentBlobs[fixtureSlug(full) + "/" + id] || null;
      return API_BASE + "/projects/" + projectPath(full) + "/attachments/" + encodeURIComponent(id) + "/content" + (download ? "?download=1" : "");
    },
    // The URL of a project's logo or banner for an <img>, or null when the
    // project view says there is none: the hub's own path, versioned by the
    // ETag; in fixture mode the image next to the project's JSON, or an upload.
    imageUrl: (full, kind, view) => {
      if (!IMAGE_KINDS.includes(kind) || !view || !view.available) return null;
      if (source === "fixtures") {
        const slug = fixtureSlug(full);
        return uploaded[slug + "/" + kind] || ("fixtures/" + encodeURIComponent(slug) + "/" + kind + ".png");
      }
      return API_BASE + "/projects/" + projectPath(full) + "/" + kind + "?v=" + encodeURIComponent(view.etag || "");
    },
    patch: (path, body) => request("PATCH", path, body || {}),
    // A body only where the route takes one (DELETE /orgs/{org}, its confirm).
    del: (path, body) => request("DELETE", path, body),
  };
})(window.Maity);
