// The fetch layer. Answers from /api/v1/... or from the fixtures in
// fixtures/ (bundled into fixtures/fixtures.js for file://). The source is
// chosen once per page load and never changes on its own: see
// context/fixtures.md.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const API_BASE = "/api/v1";

  function chooseSource() {
    const forced = new URLSearchParams(window.location.search).get("source");
    if (forced === "fixtures" || forced === "api") return forced;
    return window.location.protocol === "file:" ? "fixtures" : "api";
  }

  const source = chooseSource();

  class ApiError extends Error {
    constructor(message, status, path) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.path = path;
    }
  }

  // ---- fixture mode -------------------------------------------------------

  // A deep copy, so that writes in fixture mode change this page load only.
  let store = null;

  function fixtures() {
    if (store) return store;
    if (!window.MAITY_FIXTURES) {
      throw new ApiError("fixtures/fixtures.js is not loaded", 0, "");
    }
    store = JSON.parse(JSON.stringify(window.MAITY_FIXTURES));
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

  function keyed(file, key, path) {
    const entry = fixtures()[file][key];
    if (!entry) throw new ApiError("Not found", 404, path);
    return entry;
  }

  // [method, pattern, handler(match, body, path)]. One row per endpoint the
  // views use; the patterns are the paths below /api/v1.
  const routes = [
    ["GET", /^\/me$/, () => fixtures()["me.json"]],
    ["GET", /^\/projects\/([^/]+)$/, () => fixtures()["project.json"]],
    ["GET", /^\/projects\/([^/]+)\/requests$/, () => fixtures()["requests.json"]],
    ["POST", /^\/projects\/([^/]+)\/requests\/([^/]+)\/answer$/, (m, body, path) => {
      const req = fixtures()["requests.json"].items.find((r) => r.id === m[2]);
      if (!req) throw new ApiError("Not found", 404, path);
      if (req.status !== "open") throw new ApiError("Request is not open", 409, path);
      req.status = body.talk ? "talk" : (body.reply_id === "later" ? "deferred" : "answered");
      req.answer = {
        reply_id: body.reply_id || null,
        text: body.text || null,
        talk: !!body.talk,
        by: fixtures()["me.json"].member.id,
        on_behalf_of: null,
        at: nowIso(),
      };
      return req;
    }],
    ["GET", /^\/projects\/([^/]+)\/tasks$/, () => fixtures()["tasks.json"]],
    ["GET", /^\/projects\/([^/]+)\/members$/, () => fixtures()["members.json"]],
    ["GET", /^\/projects\/([^/]+)\/members\/([^/]+)\/credentials$/,
      (m, body, path) => keyed("credentials.json", m[2], path)],
    ["POST", /^\/projects\/([^/]+)\/credentials\/([^/]+)\/revoke$/, (m, body, path) => {
      const all = fixtures()["credentials.json"];
      for (const member of Object.keys(all)) {
        const list = all[member].items;
        const i = list.findIndex((c) => c.id === m[2]);
        if (i >= 0) {
          const [revoked] = list.splice(i, 1);
          revoked.revoked_at = nowIso();
          return revoked;
        }
      }
      throw new ApiError("Not found", 404, path);
    }],
    ["GET", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/,
      (m, body, path) => keyed("conversations.json", m[2], path)],
    ["POST", /^\/projects\/([^/]+)\/conversations\/([^/]+)\/messages$/, (m, body, path) => {
      const conv = keyed("conversations.json", m[2], path);
      const msg = {
        id: localId("msg"),
        from: fixtures()["me.json"].member.id,
        to: m[2],
        body: body.body,
        sent_at: nowIso(),
        delivered_at: null,
      };
      conv.items.push(msg);
      return msg;
    }],
  ];

  function fromFixtures(method, path, body) {
    for (const [verb, pattern, handler] of routes) {
      if (verb !== method) continue;
      const match = pattern.exec(path);
      if (match) {
        // Hand out copies, like a network answer would.
        return Promise.resolve().then(() =>
          JSON.parse(JSON.stringify(handler(match, body || {}, path))));
      }
    }
    return Promise.reject(new ApiError("No fixture for " + method + " " + path, 404, path));
  }

  // ---- API mode -----------------------------------------------------------

  async function fromApi(method, path, body) {
    const init = {
      method,
      credentials: "same-origin",
      headers: { Accept: "application/json" },
    };
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
      try {
        const data = await res.json();
        if (data && data.error) detail = data.error.message || data.error;
      } catch (ignored) {
        // Not JSON; the status text is all there is.
      }
      throw new ApiError(detail || ("HTTP " + res.status), res.status, path);
    }
    return res.status === 204 ? null : res.json();
  }

  function request(method, path, body) {
    return source === "fixtures" ? fromFixtures(method, path, body) : fromApi(method, path, body);
  }

  M.api = {
    source,
    ApiError,
    get: (path) => request("GET", path),
    post: (path, body) => request("POST", path, body || {}),
  };
})(window.Maity);
