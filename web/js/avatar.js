// A member's picture. Where the member carries an avatar URL the page may
// show (later: a forge or an upload, contract pending), that one; else a
// generated identicon: a 5×5 mirrored pattern and a hue, both from the
// member id alone, so every client draws the same picture for the same
// member. Built as SVG nodes, never from markup. Decorative: the name is
// always written next to it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const SVG = "http://www.w3.org/2000/svg";

  function svg(tag, attrs) {
    const el = document.createElementNS(SVG, tag);
    Object.entries(attrs).forEach(([k, v]) => el.setAttribute(k, String(v)));
    return el;
  }

  // FNV-1a, 32 bits: small, and the same in every browser.
  function fnv(text) {
    let x = 0x811c9dc5;
    for (const ch of String(text)) {
      x ^= ch.codePointAt(0);
      x = Math.imul(x, 0x01000193) >>> 0;
    }
    return x >>> 0;
  }

  // The cells that are on, as [column, row], for columns 0–4 (2–4 mirror 0–2).
  function cells(id) {
    const bits = fnv(id);
    const on = [];
    for (let row = 0; row < 5; row += 1) {
      for (let col = 0; col < 3; col += 1) {
        if ((bits >>> (row * 3 + col)) & 1) {
          on.push([col, row]);
          if (col < 2) on.push([4 - col, row]);
        }
      }
    }
    // An empty pattern would read as a missing picture: one cell at least.
    return on.length ? on : [[2, 2]];
  }

  const hueOf = (id) => fnv(id + "#hue") % 360;

  function identicon(id, size) {
    const box = svg("svg", { class: "avatar-svg", viewBox: "0 0 7 7", width: size, height: size, "aria-hidden": "true", focusable: "false" });
    // The hue as a custom property; the theme sets lightness and background.
    if (box.style && box.style.setProperty) box.style.setProperty("--avatar-h", String(hueOf(id)));
    box.appendChild(svg("rect", { class: "avatar-bg", x: 0, y: 0, width: 7, height: 7, rx: 1.4 }));
    cells(id).forEach(([x, y]) => box.appendChild(svg("rect", { class: "avatar-on", x: x + 1, y: y + 1, width: 1, height: 1 })));
    return box;
  }

  // member: { id, avatar_url? }. A URL the page refuses (h() allows only
  // the hub's own images) falls back to the identicon.
  M.avatar = function (member, size) {
    const px = size || 24;
    if (member && member.avatar_url) {
      try {
        return M.dom.h("img", { class: "avatar-img", src: member.avatar_url, alt: "", width: String(px), height: String(px) });
      } catch (refused) {
        // not an image the page may load: the generated one instead
      }
    }
    return identicon(member && member.id ? member.id : "?", px);
  };
  M.avatar.cells = cells;
  M.avatar.hueOf = hueOf;
})(window.Maity);
