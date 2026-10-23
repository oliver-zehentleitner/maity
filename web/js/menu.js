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
  M.icons = { gear, bell };

  // spec: { label (accessible name), face (nodes inside the button), items: [...] }
  M.menuButton = function (spec) {
    serial += 1;
    const id = "menu-" + serial;
    const list = h("ul", { class: "menu", id, role: "menu", "aria-label": spec.label });
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
        const attrs = { role: "menuitem", tabindex: "-1", class: "menu-item" };
        let el;
        if (it.disabled) {
          el = h("span", Object.assign(attrs, { "aria-disabled": "true", class: "menu-item disabled" }), it.label,
            it.why ? h("span", { class: "muted" }, " · " + it.why) : null);
        } else if (it.href) {
          el = h("a", Object.assign(attrs, { href: it.href, onclick: () => close(false) }), it.label);
        } else {
          el = h("button", Object.assign(attrs, { type: "button", onclick: () => { close(false); it.onSelect(); } }), it.label);
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
