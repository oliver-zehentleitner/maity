// The theme picked for this browser — System, Light or Dark — set on <html>
// as data-theme before the first paint: this file loads without defer from
// <head> for that. Storage may be missing or refuse (a private window,
// blocked site data): then it is System, and nothing fails.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const KEY = "maity.theme";
  const THEMES = ["system", "light", "dark"];
  const read = () => {
    try { return window.localStorage.getItem(KEY); } catch (e) { return null; }
  };
  let current = THEMES.includes(read()) ? read() : "system";
  const apply = () => {
    const root = document.documentElement;
    if (current === "system") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", current);
  };
  apply();
  M.theme = {
    THEMES,
    get: () => current,
    set: (theme) => {
      if (!THEMES.includes(theme)) return;
      current = theme;
      try {
        if (theme === "system") window.localStorage.removeItem(KEY);
        else window.localStorage.setItem(KEY, theme);
      } catch (e) {
        // Kept for this page only.
      }
      apply();
    },
  };
})(window.Maity);
