// A new deploy under an open page (docs/api.md §1.1 `Maity-Web-Version`, §16.11): every API
// answer names the dashboard the hub serves, the shell names the one this page runs. When they
// differ, a band above the header offers a reload; the page never reloads by itself
// (web/context/refresh.md d499ba75). "Later" hides the band for that version in this tab, a
// newer one brings it back. Over a reload, a typed input (a chat's draft, a note, a form) asks
// first: the dashboard keeps none of them over a reload.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;
  const ID = "new-version-banner";

  let own;          // this page's version, from the shell's meta element (undefined: not read yet)
  let shown = null; // the newer version the band stands for
  let later = null; // the version "Later" was chosen for

  function ownVersion() {
    if (own === undefined) {
      const meta = document.head && document.head.querySelector('meta[name="maity-web-version"]');
      own = (meta && meta.getAttribute("content")) || null;
    }
    return own;
  }

  // An input a reload would lose: text typed into a field of the page.
  function unsentInput() {
    const fields = document.body ? document.body.querySelectorAll("textarea, input") : [];
    return Array.from(fields).some((f) => {
      if (f.tagName === "INPUT" && !/^(|text|email|url|number|tel)$/.test((f.getAttribute("type") || "").toLowerCase())) return false;
      const value = typeof f.value === "string" ? f.value : "";
      return value.trim() !== "" && value !== (f.defaultValue || "");
    });
  }

  // The browser's own "leave the page?" while an input would be lost; one prompt, whichever
  // listener asks (js/project-message.js asks for its own body as well).
  function guard(e) { if (unsentInput()) { e.preventDefault(); e.returnValue = ""; } }

  function reload() {
    window.addEventListener("beforeunload", guard);
    M.newVersion.reloadPage();
    // Kept from the guard after a reload the reader stopped: it belongs to the click alone.
    window.setTimeout(() => window.removeEventListener("beforeunload", guard), 0);
  }

  function draw() {
    const header = document.getElementById("header");
    if (!header || !header.parentNode) return;
    const parent = header.parentNode;
    const old = Array.from(parent.childNodes).find((n) => n.id === ID);
    if (!shown || shown === later) { if (old) parent.removeChild(old); return; }
    const band = h("div", { id: ID, class: "new-version-banner", role: "status" },
      h("span", {}, M.t("new_version.text")),
      h("button", { type: "button", class: "new-version-reload", onclick: reload }, M.t("new_version.reload")),
      h("button", { type: "button", class: "secondary new-version-later", onclick: () => { later = shown; draw(); } }, M.t("new_version.later")));
    if (old) parent.replaceChild(band, old);
    else parent.insertBefore(band, header);
  }

  // Each API answer's `Maity-Web-Version` (js/api.js). Two hubs side by side during a deploy may
  // answer both values: the band stands from the first newer one until a reload or "Later".
  function seen(version) {
    const mine = ownVersion();
    if (!mine || !version || version === mine || version === shown) return;
    shown = version;
    draw();
  }

  M.newVersion = {
    seen,
    // Drawn again with every page, so the band follows a change of language.
    draw,
    // window.location.reload, here so that the smoke test can see it called.
    reloadPage: () => window.location.reload(),
    unsentInput,
  };
})(window.Maity);
