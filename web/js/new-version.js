// A new deploy under an open page (docs/api.md §1.1 `Maity-Web-Version`, §16.11): every API
// answer names the dashboard the hub serves, the shell names the one this page runs. When they
// differ, a band above the header offers a reload; the page never reloads by itself
// (web/context/refresh.md d499ba75). "Later" hides the band for that version in this tab, a
// newer one brings it back. Over a reload, input the reader typed (a chat's draft, a note, a
// changed setting) asks first: the dashboard keeps none of them over a reload.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h } = M.dom;
  const ID = "new-version-banner";

  let own;              // this page's version, from the shell's meta element (undefined: not read yet)
  let shown = null;     // the newer version the band stands for
  const later = new Set(); // the versions "Later" was chosen for: two hubs side by side may answer
                           // both of two newer ones, and neither brings the band back

  function ownVersion() {
    if (own === undefined) {
      const meta = document.head && document.head.querySelector('meta[name="maity-web-version"]');
      own = (meta && meta.getAttribute("content")) || null;
    }
    return own;
  }

  // What a reload would lose is what the reader changed, not what the page filled in: a field's
  // value is noted when the reader first comes to it (focus), and a field that differs from that
  // is typed input. A value a form sets itself (a setting read from the hub, a default) is never
  // input, a cleared field is. A sent form's fields count as unchanged again.
  const NOT_TYPED = /^(button|submit|reset|image|hidden)$/;
  const typable = (f) => f && (f.tagName === "TEXTAREA" || f.tagName === "SELECT"
    || (f.tagName === "INPUT" && !NOT_TYPED.test((f.getAttribute("type") || "").toLowerCase())));
  const stateOf = (f) => (/^(checkbox|radio)$/i.test(f.getAttribute("type") || "") ? String(!!f.checked)
    : typeof f.value === "string" ? f.value : "");
  const before = new WeakMap();
  function noted(e) { const f = e.target; if (typable(f) && !before.has(f)) before.set(f, stateOf(f)); }
  function sent(e) {
    const form = e.target;
    if (!form || !form.querySelectorAll) return;
    Array.from(form.querySelectorAll("textarea, input, select")).forEach((f) => { if (before.has(f)) before.set(f, stateOf(f)); });
  }
  document.addEventListener("focusin", noted, true);
  document.addEventListener("submit", sent, true);

  function unsentInput() {
    const fields = document.body ? document.body.querySelectorAll("textarea, input, select") : [];
    return Array.from(fields).some((f) => typable(f) && before.has(f) && stateOf(f) !== before.get(f));
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
    if (!shown || later.has(shown)) { if (old) parent.removeChild(old); return; }
    const words = M.t("new_version.text");
    // Kept as it stands while nothing it says changed: a new band would be announced again
    // (role="status") and take the focus from its buttons on every page drawn.
    if (old && old.getAttribute("data-version") === shown && old.getAttribute("data-words") === words) return;
    const band = h("div", { id: ID, class: "new-version-banner", role: "status", "data-version": shown, "data-words": words },
      h("span", {}, words),
      h("button", { type: "button", class: "new-version-reload", onclick: reload }, M.t("new_version.reload")),
      h("button", { type: "button", class: "secondary new-version-later", onclick: () => { later.add(shown); draw(); } }, M.t("new_version.later")));
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
