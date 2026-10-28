// Prints the Runners view's starter configurations for a few kinds of
// projects, with the command that writes each, as JSON: what
// tools/starter_configs.py hands to `maity runner check`. Runs js/dom.js
// and js/runners.js; generating them touches no DOM.
"use strict";

const fs = require("fs");
const path = require("path");
const vm = require("vm");

const WEB = path.resolve(__dirname, "..");
const ctx = { window: { Maity: { views: {} } }, JSON, String, Number, Date, console };
ctx.window.window = ctx.window;
vm.createContext(ctx);
for (const file of ["js/dom.js", "js/runners.js"]) {
  vm.runInContext(fs.readFileSync(path.join(WEB, file), "utf8"), ctx, { filename: file });
}
const { runnerStarterConfig: generate, runnerConfigCommand: command } = ctx.window.Maity;

const repo = (url) => ({ url });
const CASES = {
  "one-project": [{ slug: "maity", full_name: "maintainer/maity", repository: repo("https://github.com/oliver-zehentleitner/maity") }],
  // A .git suffix, a trailing slash and a host in capitals, as a forge URL may come.
  "two-projects": [
    { slug: "maity", full_name: "maintainer/maity", repository: repo("https://github.com/oliver-zehentleitner/maity.git") },
    { slug: "sample", full_name: "maintainer/sample", repository: repo("https://GitHub.com/Example/sample-shop/") },
  ],
  "no-repository": [{ slug: "maity", full_name: "maintainer/maity", repository: null }],
  "no-project": [],
};

const out = {};
for (const [name, projects] of Object.entries(CASES)) {
  const config = generate("https://hub.example", projects);
  out[name] = { config, command: command(config) };
}
process.stdout.write(JSON.stringify(out, null, 2) + "\n");
