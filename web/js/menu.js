// A menu behind a button (the header's settings and profile menus): a
// real button with aria-haspopup and aria-expanded, items as menuitems.
// Arrow keys, Home and End move between the items; Escape and Tab close
// it, and Escape puts the focus back on the button; a click elsewhere
// closes it too. Items are links (href), actions (onSelect) or a
// disabled note (disabled: true, with why).
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const { h, append, clear } = M.dom;
  const SVG = "http://www.w3.org/2000/svg";
  let serial = 0;

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
  M.icons = { gear, bell, chat, theme: themeIcon };

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
        const attrs = { role: choice ? "menuitemradio" : "menuitem", "aria-checked": choice ? String(it.checked) : null,
          tabindex: "-1", class: "menu-item" + (choice && it.checked ? " checked" : ""), title: it.title || null };
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
          el = h("button", Object.assign(attrs, { type: "button", onclick: () => { close(true); it.onSelect(); } }), it.label);
        }
        items.push(el);
        append(list, h("li", { role: "none" }, el));
      });
      list.hidden = false;
      button.setAttribute("aria-expanded", "true");
      document.addEventListener("click", outside, true);
      if (items.length) items[at === "last" ? items.length - 1 : 0].focus();
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
    return { el: box, button, close };
  };
})(window.Maity);
