// A menu behind a button (the header's settings and profile menus): a
// real button with aria-haspopup and aria-expanded, items as menuitems.
// Arrow keys, Home and End move between the items; Escape and Tab close
// it, and Escape puts the focus back on the button; a click elsewhere
// closes it too. Items are links (href), actions (onSelect) or a
// disabled note (disabled: true, with why). An item with `checkbox: true`
// and `checked` is a switch: it keeps the menu open, so several are
// switched in one go, and the focus stays on it. An item's `key` (data-key) names what it does
// independently of its words, so that a view drawing the menu anew can find the same item again.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  let serial = 0;
  // Each menu by its button, so that a view which draws a menu anew can open the new one where the
  // old one stood open (M.menuOf): the board's redraws that no action of the reader starts.
  const MENUS = new WeakMap();
  M.menuOf = (button) => MENUS.get(button) || null;

  // A gear of eight teeth, drawn from points; it takes the text colour.
  function gear(size) {
    const pts = [];
    for (let i = 0; i < 16; i += 1) {
      const a = (Math.PI * 2 * i) / 16 - Math.PI / 16;
      const r = i % 2 === 0 ? 11 : 8.6;
      pts.push((12 + r * Math.cos(a)).toFixed(2) + "," + (12 + r * Math.sin(a)).toFixed(2));
    }
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "polygon");
    body.setAttribute("points", pts.join(" "));
    body.setAttribute("class", "icon-fill");
    const hole = document.createElementNS(SVG, "circle");
    [["cx", "12"], ["cy", "12"], ["r", "3.6"], ["class", "icon-hole"]].forEach(([k, v]) => hole.setAttribute(k, v));
    svg.appendChild(body);
    svg.appendChild(hole);
    return svg;
  }
  // A bell: a dome on a rim, and the clapper below; it takes the text colour.
  function bell(size) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "path");
    body.setAttribute("d", "M12 3a6 6 0 0 0-6 6v4.2L4 16.5V18h16v-1.5l-2-3.3V9a6 6 0 0 0-6-6zm-2.2 16a2.2 2.2 0 0 0 4.4 0z");
    body.setAttribute("class", "icon-fill");
    svg.appendChild(body);
    return svg;
  }
  // A person with a star at the shoulder, for the lead; the text colour.
  function lead(size) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "path");
    body.setAttribute("d", "M10 4a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM2 20c0-3.9 3.6-6.5 8-6.5s8 2.6 8 6.5zM18.5 2l1 2.1 2.3.3-1.7 1.6.4 2.3-2-1.1-2 1.1.4-2.3-1.7-1.6 2.3-.3z");
    body.setAttribute("class", "icon-fill");
    svg.appendChild(body);
    return svg;
  }
  // A speech bubble with its tail at the lower left; it takes the text colour.
  function chat(size) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "path");
    body.setAttribute("d", "M4 3h16a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H10l-5 4v-4H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z");
    body.setAttribute("class", "icon-fill");
    svg.appendChild(body);
    return svg;
  }
  // The chat list's two actions (tsk-qgy2tb3w3x93), drawn by maity-artwork-claude-001#gj6k
  // (tsk-kbk47n2hct2y; the owner's picks group-b and project-a): two people with a plus for a new
  // group chat, a loudspeaker for a message to the project. One path each; the text colour.
  function drawn(size, d) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "path");
    body.setAttribute("d", d);
    body.setAttribute("class", "icon-fill");
    body.setAttribute("fill-rule", "evenodd");
    svg.appendChild(body);
    return svg;
  }
  const newGroup = (size) => drawn(size, "M23.73 5.74 23.50 5.01 23.14 4.33 22.66 3.74 22.07 3.26 21.39 2.90 20.66 2.67 19.90 2.60 19.14 2.67 18.41 2.90 17.73 3.26 17.14 3.74 16.66 4.33 16.30 5.01 16.07 5.74 16 6.50 16.07 7.26 16.30 7.99 16.66 8.67 17.14 9.26 17.73 9.74 18.41 10.10 19.14 10.33 19.90 10.40 20.66 10.33 21.39 10.10 22.07 9.74 22.66 9.26 23.14 8.67 23.50 7.99 23.73 7.26 23.80 6.50zM19.05 8.80 19.05 7.35 17.60 7.35 17.60 5.65 19.05 5.65 19.05 4.20 20.75 4.20 20.75 5.65 22.20 5.65 22.20 7.35 20.75 7.35 20.75 8.80zM9.97 8.75 9.69 8.23 9.32 7.78 8.87 7.41 8.35 7.13 7.79 6.96 7.20 6.90 6.61 6.96 6.05 7.13 5.53 7.41 5.08 7.78 4.71 8.23 4.43 8.75 4.26 9.31 4.20 9.90 4.26 10.49 4.43 11.05 4.71 11.57 5.08 12.02 5.53 12.39 6.05 12.67 6.61 12.84 7.20 12.90 7.79 12.84 8.35 12.67 8.87 12.39 9.32 12.02 9.69 11.57 9.97 11.05 10.14 10.49 10.20 9.90 10.14 9.31zM16.75 10.51 16.04 9.83 15.57 9.19 15.21 9.03 14.73 8.92 14.24 8.91 13.75 8.99 13.29 9.16 12.87 9.42 12.51 9.76 12.22 10.16 12.01 10.61 11.90 11.09 11.89 11.58 11.97 12.07 12.14 12.53 12.40 12.95 12.74 13.31 13.14 13.60 13.59 13.81 14.07 13.92 14.56 13.93 15.05 13.85 15.51 13.68 15.93 13.42 16.29 13.08 16.58 12.68 16.79 12.23 16.87 11.91 16.91 11.58 16.90 11.09zM2.87 15.94 2.56 16.40 2.32 16.89 2.14 17.41 2.04 17.95 2 18.50 2.04 19.25 2.09 19.50 12.31 19.50 12.36 19.25 12.40 18.70 12.36 17.95 12.26 17.41 12.08 16.89 11.84 16.40 11.53 15.94 11.17 15.53 10.76 15.17 10.30 14.86 9.81 14.62 9.29 14.44 8.75 14.34 8.20 14.30 6.20 14.30 5.65 14.34 5.11 14.44 4.59 14.62 4.10 14.86 3.64 15.17 3.23 15.53zM13.30 17.06 13.44 17.74 13.50 18.43 13.44 19.48 18.70 19.48 18.77 18.81 18.74 18.18 18.65 17.73 18.50 17.29 18.30 16.88 18.04 16.50 17.73 16.15 17.39 15.85 17 15.59 16.59 15.38 16.15 15.24 15.70 15.15 15.24 15.12 13.56 15.12 13.10 15.15 12.65 15.24 12.43 15.31 12.82 15.91 13.12 16.54z");
  const writeProject = (size) => drawn(size, "M1.74 8.49 1.47 8.65 1.25 8.87 1.09 9.14 1.04 9.29 1 9.60 1 14.40 1.04 14.71 1.09 14.86 1.25 15.13 1.35 15.25 1.47 15.35 1.74 15.51 2.04 15.59 3 15.60 3.31 15.56 3.25 15.57 14 20.50 14 3.50 3.25 8.43 3.31 8.44 3 8.40 2.20 8.40 2.04 8.41zM18.13 8.28 17.91 8.13 17.66 8.05 17.40 8.03 17.15 8.08 16.91 8.20 16.68 8.42 16.55 8.65 16.48 8.90 16.48 9.16 16.55 9.41 16.68 9.64 17.16 10.22 17.37 10.58 17.53 10.97 17.67 11.58 17.69 12.21 17.64 12.62 17.53 13.03 17.37 13.42 17.16 13.78 16.60 14.47 16.50 14.71 16.47 14.90 16.50 15.23 16.68 15.58 16.97 15.84 17.34 15.96 17.73 15.94 18.08 15.76 18.41 15.43 18.82 14.89 19.16 14.30 19.30 13.99 19.52 13.35 19.66 12.68 19.70 12 19.66 11.32 19.52 10.65 19.42 10.33 19.16 9.70 18.82 9.11 18.41 8.57zM20.88 6.54 20.67 6.38 20.36 6.26 20.10 6.25 19.85 6.30 19.61 6.41 19.38 6.63 19.24 6.86 19.17 7.18 19.19 7.44 19.27 7.69 19.82 8.44 20.04 8.80 20.41 9.55 20.68 10.34 20.85 11.16 20.89 11.58 20.89 12.42 20.85 12.84 20.68 13.66 20.56 14.06 20.41 14.45 20.04 15.20 19.82 15.56 19.30 16.26 19.18 16.63 19.20 17.02 19.38 17.37 19.56 17.55 19.73 17.65 20.10 17.75 20.36 17.74 20.55 17.68 20.88 17.46 21.48 16.67 22.03 15.72 22.26 15.21 22.61 14.17 22.83 13.10 22.88 12.55 22.88 11.45 22.83 10.90 22.74 10.36 22.45 9.30 22.03 8.28 21.77 7.80 21.48 7.33zM4.72 20.01 4.93 20.37 5.07 20.53 5.40 20.79 5.59 20.88 5.79 20.95 6.20 21 7 21 7.41 20.95 7.80 20.79 8.13 20.53 8.27 20.37 8.48 20.01 8.55 19.81 8.59 19.61 8.60 19.24 4.60 17.40 4.60 19.40 4.61 19.61z");
  // A plus and a cross, drawn as two bars, so they sit in the button's middle in every browser:
  // as text glyphs ("+", "×") they followed the font's metrics and sat off-centre in Edge on
  // Windows (tsk-m9ew7v609fq0). They take the text colour.
  function bars(size, d) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const body = document.createElementNS(SVG, "path");
    body.setAttribute("d", d);
    body.setAttribute("class", "icon-fill");
    svg.appendChild(body);
    return svg;
  }
  const plus = (size) => bars(size, "M10.5 4h3v6.5H20v3h-6.5V20h-3v-6.5H4v-3h6.5z");
  const close = (size) => bars(size, "M6.1 4L12 9.9 17.9 4 20 6.1 14.1 12 20 17.9 17.9 20 12 14.1 6.1 20 4 17.9 9.9 12 4 6.1z");
  // Full screen: four corners pointing out; leaving it, the same corners pointing in.
  const expand = (size) => bars(size, "M3 3h7v2.5H5.5V10H3zM14 3h7v7h-2.5V5.5H14zM3 14h2.5v4.5H10V21H3zM18.5 14H21v7h-7v-2.5h4.5z");
  const collapse = (size) => bars(size, "M7.5 3H10v7H3V7.5h4.5zM14 3h2.5v4.5H21V10h-7zM3 14h7v7H7.5v-4.5H3zM14 14h7v2.5h-4.5V21H14z");
  // The theme: a circle half filled (the system's), a sun, a moon.
  function themeIcon(theme, size) {
    const svg = document.createElementNS(SVG, "svg");
    [["viewBox", "0 0 24 24"], ["width", String(size)], ["height", String(size)], ["aria-hidden", "true"], ["focusable", "false"], ["class", "icon"]]
      .forEach(([k, v]) => svg.setAttribute(k, v));
    const path = document.createElementNS(SVG, "path");
    const d = theme === "light"
      ? "M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM11 1h2v3h-2zM11 20h2v3h-2zM1 11h3v2H1zM20 11h3v2h-3zM4.2 5.6l1.4-1.4 2.1 2.1-1.4 1.4zM16.3 17.7l1.4-1.4 2.1 2.1-1.4 1.4zM4.2 18.4l2.1-2.1 1.4 1.4-2.1 2.1zM16.3 6.3l2.1-2.1 1.4 1.4-2.1 2.1z"
      : theme === "dark"
      ? "M14.5 2.5a9.5 9.5 0 1 0 7 15.9A8 8 0 0 1 14.5 2.5z"
      : "M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm0 2v16a8 8 0 0 1 0-16z";
    path.setAttribute("d", d);
    path.setAttribute("class", "icon-fill");
    path.setAttribute("fill-rule", "evenodd");
    svg.appendChild(path);
    return svg;
  }
  // A closed padlock for a private project (tsk-5t3qd0m9rj6r): the shackle's inside cut out of
  // one path, so it takes the text colour in both themes.
  function lock(size) {
    const svg = bars(size, "M7 10V7a5 5 0 0 1 10 0v3h1a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1v-9a1 1 0 0 1 1-1zm2.5 0h5V7a2.5 2.5 0 0 0-5 0z");
    svg.firstChild.setAttribute("fill-rule", "evenodd");
    return svg;
  }
  M.icons = { gear, bell, chat, lead, newGroup, writeProject, plus, close, expand, collapse, lock, theme: themeIcon };

  // spec: { label (accessible name), face (nodes inside the button), items: [...],
  // listLabel (the list's name, when the button's label carries a state that changes) }
  M.menuButton = function (spec) {
    serial += 1;
    const id = "menu-" + serial;
    const list = h("ul", { class: "menu", id, role: "menu", "aria-label": spec.listLabel || spec.label });
    list.hidden = true;
    const button = h("button", {
      type: "button",
      class: "menu-button " + (spec.class || ""),
      "aria-haspopup": "menu",
      "aria-expanded": "false",
      "aria-controls": id,
      "aria-label": spec.label,
      title: spec.label,
    }, spec.face);
    const box = h("div", { class: "menu-box" }, button, list);
    let items = [];

    function close(refocus) {
      if (list.hidden) return;
      list.hidden = true;
      button.setAttribute("aria-expanded", "false");
      document.removeEventListener("click", outside, true);
      if (refocus) button.focus();
    }
    function outside(e) {
      if (!box.contains || !box.contains(e.target)) close(false);
    }
    function open(at) {
      clear(list);
      items = [];
      spec.items().forEach((it) => {
        if (it.separator) { append(list, h("li", { role: "separator", class: "menu-sep" })); return; }
        // An item of a choice (checked given) says whether it is the current one.
        const choice = typeof it.checked === "boolean";
        const attrs = { role: choice ? (it.checkbox ? "menuitemcheckbox" : "menuitemradio") : "menuitem", "aria-checked": choice ? String(it.checked) : null,
          tabindex: "-1", class: "menu-item" + (choice && it.checked ? " checked" : ""), title: it.title || null, "data-key": it.key || null };
        let el;
        if (it.disabled) {
          el = h("span", Object.assign(attrs, { "aria-disabled": "true", class: "menu-item disabled" }), it.label,
            it.why ? h("span", { class: "muted" }, " · " + it.why) : null);
        } else if (it.href) {
          // A link to the page shown says so, as the tabs do.
          el = h("a", Object.assign(attrs, { href: it.href, "aria-current": it.current ? "page" : null, onclick: () => close(false) }), it.label);
        } else {
          // Back on the button before the action runs: whatever it does next
          // (moves the focus itself, fails, redraws) starts from a visible control.
          const index = items.length;
          el = h("button", Object.assign(attrs, { type: "button", onclick: it.checkbox
            ? () => { it.onSelect(); open(index); }
            : () => { close(true); it.onSelect(); } }), it.label);
        }
        items.push(el);
        append(list, h("li", { role: "none" }, el));
      });
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      document.addEventListener("click", outside, true);
      if (items.length) items[typeof at === "number" ? Math.min(at, items.length - 1) : at === "last" ? items.length - 1 : 0].focus();
    }
    const move = (step) => {
      const at = items.indexOf(document.activeElement);
      const next = (at + step + items.length) % items.length;
      items[next].focus();
    };

    button.addEventListener("click", () => (list.hidden ? open("first") : close(true)));
    button.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); open(e.key === "ArrowUp" ? "last" : "first"); }
    });
    list.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); close(true); }
      else if (e.key === "Tab") close(false);
      else if (e.key === "ArrowDown") { e.preventDefault(); move(1); }
      else if (e.key === "ArrowUp") { e.preventDefault(); move(-1); }
      else if (e.key === "Home") { e.preventDefault(); items[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); items[items.length - 1].focus(); }
    });
    const api = { el: box, button, close, open };
    MENUS.set(button, api);
    return api;
  };
})(window.Maity);
