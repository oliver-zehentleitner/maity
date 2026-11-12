// The version a dashboard file is asked for under, for the files a script loads later by a
// name it builds: an i18n catalog, Keep the Why's files, a brand picture. Served by the hub,
// the shell lists their versions in a data block (`#maity-assets`, docs/api.md §16.11), and a
// file asked for with `?v=<version>` may be kept by the browser for good. Without the block
// (fixture mode, file://), or for a file it does not list, the name stays as it is.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const VERSION = /^[0-9a-f]{16}$/;
  let versions = null;
  function read() {
    if (versions) return versions;
    versions = {};
    try {
      const block = window.document.getElementById("maity-assets");
      const parsed = block ? JSON.parse(block.textContent) : null;
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) versions = parsed;
    } catch (e) {
      // A block that does not parse: every name as it is.
    }
    return versions;
  }
  // "?v=<version>" for a path under /assets/ ("js/i18n/de.js"), "" when it has none.
  function assetQuery(path) {
    const all = read();
    const version = Object.hasOwn(all, path) ? all[path] : null;
    return typeof version === "string" && VERSION.test(version) ? "?v=" + version : "";
  }

  M.assetQuery = assetQuery;
})(window.Maity);
