// The fixture hub's answers to tools/shape-requests.json, as JSON on stdout, for
// tools/check.py to compare with the hub's recorded shapes. It runs api.js in fixture
// mode with no page around it, as smoke does with a page.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.resolve(__dirname, "..");
const spec = JSON.parse(fs.readFileSync(path.join(__dirname, "shape-requests.json"), "utf8"));
const win = {
  location: { protocol: "file:", search: "", hash: "" },
  addEventListener() {}, removeEventListener() {},
  setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {},
  // errorWords without js/errors.js and its catalog: the message as the fixture hub gives it, so a refusal names its error.
  Maity: { i18n: { follow: () => Promise.resolve() }, errorWords: (code, details, message) => message },
};
win.window = win;
const ctx = { window: win, document: { cookie: "", addEventListener() {} }, URL, URLSearchParams, console, Promise, JSON, Date, Set, Map, Object, Array, Number, String, Error };
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(WEB, "fixtures/fixtures.js"), "utf8"), ctx, { filename: "fixtures.js" });
vm.runInContext(fs.readFileSync(path.join(WEB, "js/api.js"), "utf8"), ctx, { filename: "js/api.js" });
const api = win.Maity.api;
const fill = (p) => p.replace(/\{(\w+)\}/g, (_, k) => spec.fixture_ids[k]);
// A body's {placeholders} too, as the hub test fills them with its own ids.
const filled = (v) => typeof v === "string" ? fill(v)
  : Array.isArray(v) ? v.map(filled)
  : v && typeof v === "object" ? Object.fromEntries(Object.entries(v).map(([k, x]) => [k, filled(x)])) : v;

(async () => {
  const out = [];
  for (const r of spec.requests) {
    const at = fill(r.path);
    const call = { GET: () => api.get(at), DELETE: () => api.del(at), POST: () => api.post(at, filled(r.body)), PATCH: () => api.patch(at, filled(r.body)) }[r.method];
    try {
      out.push({ method: r.method, path: r.path, answer: await call() });
    } catch (err) {
      out.push({ method: r.method, path: r.path, error: String(err && (err.code || err.message) || err) });
    }
  }
  process.stdout.write(JSON.stringify(out));
})();
