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
  // ?no_projects=1 starts it with no memberships, to show the empty state.
  const fixtureNoProjects = params.get("no_projects") === "1";

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
  const PRESETS = {
    hierarchical: {
      claim_policy: "self-claim", done_authority: "reviewer", contract_arbiter: "role:admin",
      tag_authority: "human", steward_writes: "cards_only", lease_seconds: 7200,
    },
    solo: {
      claim_policy: "self-claim", done_authority: "holder", contract_arbiter: null,
      tag_authority: "human", steward_writes: "cards_only", lease_seconds: 7200,
    },
  };

  // [method, pattern, handler(match, body, path, query)]. One row per
  // endpoint the views use; the patterns match the path below /api/v1
  // without the query string.
  const routes = [
    ["GET", /^\/auth\/session$/, (m, body, path) => {
      if (!fixtureSignedIn) fail(401, "unauthenticated", "Not signed in", path);
      return fixtures()["auth-session.json"];
    }],
    ["POST", /^\/auth\/login$/, (m, body, path) => {
      if (body.handle !== me().member.handle || !body.password) {
        fail(401, "unauthenticated", "Handle or password is wrong", path);
      }
      fixtureSignedIn = true;
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
      });
      data.server_time = nowIso();
      return data;
    }],
    ["GET", /^\/agents$/, () => fixtures()["agents.json"]],
    // The cross-project inbox: every open request waiting for this human,
    // each with its project.
    ["GET", /^\/requests$/, () => ({
      items: me().projects.flatMap((p) => openFor(p.slug).map((r) => Object.assign(
        { project: { slug: p.slug, name: p.name, state: project(p.slug, "").state } }, r))),
      next_cursor: null,
    })],
    // The forge rule as the hub applies it, with github.com as the one
    // configured forge.
    ["POST", /^\/projects$/, (m, body, path) => {
      const fields = {};
      if (!SLUG.test(body.slug || "")) fields.slug = "string_pattern_mismatch";
      else if (fixtures()[body.slug + "/project.json"]) fields.slug = "taken";
      if (!body.name || !body.name.trim()) fields.name = "string_too_short";
      const url = body.repository ? String(body.repository.url || "").replace(/\/+$/, "") : null;
      if (url !== null && !/^https:\/\/github\.com\/[^/\s]+\/[^/\s]+$/.test(url)) {
        fields["repository.url"] = "not_a_configured_forge";
      }
      const preset = body.policy && body.policy.preset ? body.policy.preset : "hierarchical";
      if (!PRESETS[preset]) fields["policy.preset"] = "unknown";
      if (Object.keys(fields).length) fail(400, "invalid", "the request does not validate", path, { fields });
      const owner = me().member;
      const created = {
        slug: body.slug, name: body.name, state: "build", state_note: null, state_changed_at: nowIso(),
        repository: url === null ? null : {
          url, default_branch: body.repository.default_branch || "main", forge: "github", probe_configured: false,
        },
        keep_the_why: Boolean(body.keep_the_why),
        policy: Object.assign({}, PRESETS[preset], {
          preset, contract_arbiter: PRESETS[preset].contract_arbiter || owner.id,
        }),
        absence: null, settings: { release_checklist: [] }, rules_version: 1, created_at: nowIso(),
      };
      const data = fixtures();
      const empty = { items: [], next_cursor: null };
      data[body.slug + "/project.json"] = created;
      data[body.slug + "/members.json"] = { items: [Object.assign({}, owner, {
        role: "owner", reports_to: null, areas: ["/"], capabilities: [], last_seen_at: nowIso(),
        presence: "online", paused: null, joined_at: nowIso(),
      })], next_cursor: null };
      ["requests", "tasks", "joins"].forEach((name) => { data[body.slug + "/" + name + ".json"] = Object.assign({}, empty); });
      data[body.slug + "/credentials.json"] = {};
      data[body.slug + "/conversations.json"] = {};
      me().projects.push({ slug: body.slug, name: body.name, state: "build", role: "owner", open_requests: 0 });
      return created;
    }],
    ["GET", /^\/projects\/([^/]+)$/, (m, body, path) => project(m[1], path)],
    ["PATCH", /^\/projects\/([^/]+)$/, (m, body, path) => {
      const p = project(m[1], path);
      if ("state" in body) {
        if (!body.reason) fail(400, "invalid", "A state change needs a reason", path, { fields: { reason: "required" } });
        p.state = body.state;
        p.state_note = body.state_note || null;
        p.state_changed_at = nowIso();
      }
      if ("absence" in body) p.absence = body.absence;
      return p;
    }],
    // Fixture mode has no other writers: the log stays empty and the head
    // is 0.
    ["GET", /^\/projects\/([^/]+)\/events$/, (m, body, path, query) => {
      project(m[1], path);
      const after = query.get("after");
      return { items: [], cursor: after === "latest" ? 0 : Number(after || 0), server_time: nowIso(), superseded: false };
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
    ["GET", /^\/projects\/([^/]+)\/tasks$/, (m, body, path, query) => {
      const keep = statusFilter(query, "all");
      return { items: file(m[1], "tasks.json", path).items.filter(keep), next_cursor: null };
    }],
    ["GET", /^\/projects\/([^/]+)\/members$/, (m, body, path) => file(m[1], "members.json", path)],
    ["PATCH", /^\/projects\/([^/]+)\/members\/([^/]+)$/, (m, body, path) => {
      const target = member(m[1], m[2], path);
      if ("paused" in body) {
        target.paused = body.paused ? { reason: body.paused.reason, since: nowIso(), by: me().member.id } : null;
        target.presence = target.paused ? "paused" : (target.session ? "online" : "offline");
      }
      return target;
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
    ["GET", /^\/projects\/([^/]+)\/joins$/, (m, body, path) => file(m[1], "joins.json", path)],
    // The join line is made up here and shown once, as the hub would.
    ["POST", /^\/projects\/([^/]+)\/joins$/, (m, body, path) => {
      let agentId = body.agent && body.agent.id;
      if (!agentId) {
        if (!body.agent || !body.agent.handle) fail(400, "invalid", "agent needs an id or a handle", path, { fields: { agent: "required" } });
        agentId = localId("agt");
        fixtures()["agents.json"].items.push({
          id: agentId, handle: body.agent.handle, display_name: body.agent.display_name || body.agent.handle,
          owner_id: me().member.id, git_identity: null, memberships: [], created_at: nowIso(),
        });
      }
      const id = localId("join");
      const ttl = Math.min(body.ttl_seconds || 900, 3600);
      const expires = new Date(Date.now() + ttl * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
      const url = "https://maity.example/j/FIXTURE-" + id;
      file(m[1], "joins.json", path).items.unshift({
        id, agent_id: agentId, role: body.role || "member", created_by: me().member.id,
        created_at: nowIso(), expires_at: expires, used_at: null, burned: false, revoked_at: null,
      });
      return {
        id, join_url: url, code: "FIXT-URE0-0000", paste_line: "maity join " + url + " --code FIXT-URE0-0000",
        agent_id: agentId, project: m[1], expires_at: expires,
      };
    }],
    ["DELETE", /^\/projects\/([^/]+)\/joins\/([^/]+)$/, (m, body, path) => {
      const j = file(m[1], "joins.json", path).items.find((x) => x.id === m[2]);
      if (!j) fail(404, "not_found", "Not found", path);
      if (!j.revoked_at) j.revoked_at = nowIso();
      return j;
    }],
    ["GET", /^\/projects\/([^/]+)\/conversations$/, (m, body, path) => {
      const all = file(m[1], "conversations.json", path);
      return {
        items: Object.keys(all).map((agentId) => {
          const items = all[agentId].items;
          return {
            agent_id: agentId,
            last_message_at: items.length ? items[items.length - 1].sent_at : null,
            unread: items.filter((x) => x.from === agentId && !x.seen_by_human).length,
          };
        }),
        next_cursor: null,
      };
    }],
    ["GET", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/, (m, body, path, query) => {
      const conv = keyed(m[1], "conversations.json", m[2], path);
      const after = Number(query.get("after") || 0);
      conv.items.forEach((x) => { x.seen_by_human = true; });
      return {
        items: conv.items.filter((x) => x.seq > after).map((x) => {
          const copy = Object.assign({}, x);
          delete copy.seen_by_human;
          return copy;
        }),
        cursor: conv.items.length ? conv.items[conv.items.length - 1].seq : null,
      };
    }],
    ["POST", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/, (m, body, path) => {
      const conv = keyed(m[1], "conversations.json", m[2], path);
      const last = conv.items.length ? conv.items[conv.items.length - 1].seq : 5000;
      const msg = {
        id: "evt-" + (last + 1), seq: last + 1, conversation_id: m[2],
        from: me().member.id, to: m[2], body: body.body, sent_at: nowIso(), delivered_at: null,
      };
      conv.items.push(Object.assign({ seen_by_human: true }, msg));
      return msg;
    }],
  ];

  function fromFixtures(method, fullPath, body) {
    const q = fullPath.indexOf("?");
    const path = q < 0 ? fullPath : fullPath.slice(0, q);
    const query = new URLSearchParams(q < 0 ? "" : fullPath.slice(q + 1));
    return loadFixtures().then(() => {
      if (!fixtureSignedIn && !path.startsWith("/auth/")) {
        fail(401, "unauthenticated", "Not signed in", fullPath);
      }
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

  async function fromApi(method, path, body) {
    const init = {
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
    // Every POST, PATCH and DELETE of a cookie session carries the token;
    // without one the hub answers 403 csrf_mismatch.
    if (method !== "GET" && method !== "HEAD") {
      const token = csrfToken();
      if (token) init.headers["X-CSRF-Token"] = token;
    }
    if (body !== undefined) {
      init.headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(body);
    }
    let res;
    try {
      res = await fetch(API_BASE + path, init);
    } catch (err) {
      throw new ApiError("The hub did not answer: " + err.message, 0, path);
    }
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
    return res.json();
  }

  function request(method, path, body) {
    const p = source === "fixtures" ? fromFixtures(method, path, body) : fromApi(method, path, body);
    if (path === "/auth/session") {
      return p.then((s) => { sessionCsrf = s.csrf_token || null; return s; });
    }
    return p;
  }

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

  M.api = {
    source,
    ApiError,
    get: (path) => request("GET", path),
    getAll,
    post: (path, body) => request("POST", path, body || {}),
    patch: (path, body) => request("PATCH", path, body || {}),
    del: (path) => request("DELETE", path),
  };
})(window.Maity);
