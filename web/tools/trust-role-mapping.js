// The trust × role mapping at the API boundary (js/api.js, until the full UI of
// tsk-tx9qcehevfnk): through the real M.api request path with a controlled fetch,
// tokens and single-role names are translated in their fields only, never in
// free text. Run: node tools/trust-role-mapping.js <web dir>
const vm = require("vm"), fs = require("fs"), path = require("path"), assert = require("assert");
const sent = [];
let answer = {};
const fetch = async (url, init) => {
  sent.push({ url, body: init.body ? JSON.parse(init.body) : undefined });
  return { ok: true, status: 200, headers: { get: () => null }, json: async () => JSON.parse(JSON.stringify(answer)) };
};
const window = { location: { protocol: "https:", search: "", origin: "https://hub.example", pathname: "/" } };
const document = { cookie: "", createElement: () => ({}), head: { appendChild: () => {} } };
vm.runInNewContext(fs.readFileSync(path.join(process.argv[2], "js/api.js"), "utf8"), {
  window, document, fetch, console, URLSearchParams, Promise, Date, Set, Map, JSON, Object, Array, Error,
  encodeURIComponent, decodeURIComponent, setTimeout, clearTimeout, AbortController,
});
const M = window.Maity;
(async () => {
  // Out: a message's text stays as written; its addressee goes out in the new sense.
  answer = {};
  await M.api.post("/projects/o/p/events", { kind: "message", to: "role:admin", body: "role:admin", summary: "role:member" });
  assert.deepStrictEqual(sent[0].body, { kind: "message", to: "trust:admin", body: "role:admin", summary: "role:member" });
  // Out: a single-role name in a membership body becomes trust and role; ticker tokens too.
  await M.api.post("/projects/o/p/joins", { agent: { handle: "a", display_name: "A" }, role: "proxy" });
  assert.deepStrictEqual(sent[1].body.trust, "admin");
  assert.deepStrictEqual(sent[1].body.role, "proxy");
  await M.api.patch("/projects/o/p", { settings: { ticker: { contract_implementers: { "6": ["role:member", "area:hub/"] } } } });
  assert.deepStrictEqual(sent[2].body.settings.ticker.contract_implementers["6"], ["role:coder", "area:hub/"]);
  // In: free text comes back untouched; tokens in token fields and roles read back.
  answer = {
    body: "trust:owner", summary: "role:coder", name: "trust:admin",
    audience: ["trust:admin", "role:coder", "all"], to: "trust:owner",
    member: { trust: "admin", role: "proxy", display_name: "role:coder" },
    guest: { trust: "guest", role: "reviewer" },
  };
  const got = await M.api.get("/projects/o/p/events");
  assert.strictEqual(got.body, "trust:owner");
  assert.strictEqual(got.summary, "role:coder");
  assert.strictEqual(got.name, "trust:admin");
  assert.deepStrictEqual(got.audience, ["role:admin", "role:member", "all"]);
  assert.strictEqual(got.to, "role:owner");
  assert.strictEqual(got.member.role, "proxy");
  assert.strictEqual(got.member.display_name, "role:coder");
  assert.strictEqual(got.guest.role, "guest");
  console.log("Trust × role mapping: token fields only, free text untouched, roles both ways PASS");
})().catch((err) => { console.error(err); process.exit(1); });
