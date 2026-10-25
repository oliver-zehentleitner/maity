// QR codes for the device-code URL (docs/api.md §2.6.7: made in the
// dashboard's own code, no third-party script). Model 2, byte mode, error
// correction level M, versions 1 to 10: up to 213 bytes, far more than a
// sign-in URL needs. The steps follow ISO/IEC 18004: data bits, Reed–Solomon
// blocks interleaved, the function patterns, the codewords in the zigzag,
// then the mask with the lowest penalty and the format bits for it.
"use strict";

window.Maity = window.Maity || {};

(function (M) {
  const MAX_VERSION = 10;
  // Level M, index = version (ISO/IEC 18004 table 9).
  const ECC_PER_BLOCK = [-1, 10, 16, 26, 18, 24, 16, 18, 22, 22, 26];
  const BLOCKS = [-1, 1, 1, 1, 2, 2, 4, 4, 4, 5, 5];
  const FORMAT_BITS_M = 0;

  // Modules left for data and error correction once the patterns are drawn.
  function rawModules(ver) {
    let n = (16 * ver + 128) * ver + 64;
    if (ver >= 2) {
      const align = Math.floor(ver / 7) + 2;
      n -= (25 * align - 10) * align - 55;
      if (ver >= 7) n -= 36;
    }
    return n;
  }
  const dataCodewords = (ver) => Math.floor(rawModules(ver) / 8) - ECC_PER_BLOCK[ver] * BLOCKS[ver];

  // GF(256) with the polynomial 0x11D.
  function mul(x, y) {
    let z = 0;
    for (let i = 7; i >= 0; i--) {
      z = (z << 1) ^ ((z >>> 7) * 0x11d);
      z ^= ((y >>> i) & 1) * x;
    }
    return z & 0xff;
  }
  function divisor(degree) {
    const result = new Array(degree).fill(0);
    result[degree - 1] = 1;
    let root = 1;
    for (let i = 0; i < degree; i++) {
      for (let j = 0; j < degree; j++) {
        result[j] = mul(result[j], root);
        if (j + 1 < degree) result[j] ^= result[j + 1];
      }
      root = mul(root, 0x02);
    }
    return result;
  }
  function remainder(data, div) {
    const result = new Array(div.length).fill(0);
    for (const b of data) {
      const factor = b ^ result.shift();
      result.push(0);
      for (let i = 0; i < div.length; i++) result[i] ^= mul(div[i], factor);
    }
    return result;
  }

  function utf8(text) {
    const out = [];
    for (const ch of text) {
      const c = ch.codePointAt(0);
      if (c < 0x80) out.push(c);
      else if (c < 0x800) out.push(0xc0 | (c >> 6), 0x80 | (c & 63));
      else if (c < 0x10000) out.push(0xe0 | (c >> 12), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
      else out.push(0xf0 | (c >> 18), 0x80 | ((c >> 12) & 63), 0x80 | ((c >> 6) & 63), 0x80 | (c & 63));
    }
    return out;
  }

  // Mode, count, bytes, terminator, padding: the data codewords of a version.
  function dataBits(bytes, ver) {
    const bits = [];
    const put = (value, n) => { for (let i = n - 1; i >= 0; i--) bits.push((value >>> i) & 1); };
    put(0x4, 4);
    put(bytes.length, ver <= 9 ? 8 : 16);
    bytes.forEach((b) => put(b, 8));
    const capacity = dataCodewords(ver) * 8;
    put(0, Math.min(4, capacity - bits.length));
    put(0, (8 - (bits.length % 8)) % 8);
    const words = [];
    for (let i = 0; i < bits.length; i += 8) words.push(bits.slice(i, i + 8).reduce((a, b) => (a << 1) | b, 0));
    for (let pad = 0xec; words.length < dataCodewords(ver); pad ^= 0xec ^ 0x11) words.push(pad);
    return words;
  }

  function interleaved(data, ver) {
    const blocks = BLOCKS[ver];
    const eccLen = ECC_PER_BLOCK[ver];
    const raw = Math.floor(rawModules(ver) / 8);
    const short = blocks - (raw % blocks);
    const shortLen = Math.floor(raw / blocks);
    const div = divisor(eccLen);
    const parts = [];
    for (let i = 0, k = 0; i < blocks; i++) {
      const dat = data.slice(k, k + shortLen - eccLen + (i < short ? 0 : 1));
      k += dat.length;
      const ecc = remainder(dat, div);
      if (i < short) dat.push(0);
      parts.push(dat.concat(ecc));
    }
    const out = [];
    for (let i = 0; i < parts[0].length; i++) {
      parts.forEach((p, j) => { if (i !== shortLen - eccLen || j >= short) out.push(p[i]); });
    }
    return out;
  }

  function alignment(ver, size) {
    if (ver === 1) return [];
    const n = Math.floor(ver / 7) + 2;
    const step = Math.ceil((ver * 4 + 4) / (n * 2 - 2)) * 2;
    const result = [6];
    for (let pos = size - 7; result.length < n; pos -= step) result.splice(1, 0, pos);
    return result;
  }

  const MASKS = [
    (x, y) => (x + y) % 2 === 0,
    (x, y) => y % 2 === 0,
    (x) => x % 3 === 0,
    (x, y) => (x + y) % 3 === 0,
    (x, y) => (Math.floor(x / 3) + Math.floor(y / 2)) % 2 === 0,
    (x, y) => ((x * y) % 2) + ((x * y) % 3) === 0,
    (x, y) => (((x * y) % 2) + ((x * y) % 3)) % 2 === 0,
    (x, y) => (((x + y) % 2) + ((x * y) % 3)) % 2 === 0,
  ];

  // The four penalty rules of ISO/IEC 18004 §7.8.3.
  function penalty(m) {
    const size = m.length;
    let score = 0;
    const lines = [];
    for (let i = 0; i < size; i++) {
      lines.push(m[i]);
      lines.push(m.map((row) => row[i]));
    }
    const finder = [true, false, true, true, true, false, true];
    for (const line of lines) {
      for (let i = 0, run = 1; i < size; i++) {
        if (i + 1 < size && line[i + 1] === line[i]) run++;
        else { if (run >= 5) score += run - 2; run = 1; }
      }
      for (let i = 0; i + 7 <= size; i++) {
        if (!finder.every((v, k) => line[i + k] === v)) continue;
        const before = i >= 4 && [1, 2, 3, 4].every((k) => !line[i - k]);
        const after = i + 11 <= size && [7, 8, 9, 10].every((k) => !line[i + k]);
        const edgeBefore = i < 4 && line.slice(0, i).every((v) => !v);
        const edgeAfter = i + 11 > size && line.slice(i + 7).every((v) => !v);
        if (before || after || edgeBefore || edgeAfter) score += 40;
      }
    }
    for (let y = 0; y + 1 < size; y++) {
      for (let x = 0; x + 1 < size; x++) {
        const c = m[y][x];
        if (c === m[y][x + 1] && c === m[y + 1][x] && c === m[y + 1][x + 1]) score += 3;
      }
    }
    const dark = m.reduce((n, row) => n + row.filter(Boolean).length, 0);
    score += 10 * Math.floor(Math.abs(dark * 20 - size * size * 10) / (size * size));
    return score;
  }

  // The QR code of `text` as rows of booleans (true = dark), without the
  // quiet zone. opts.version and opts.mask fix what is otherwise chosen.
  function matrix(text, opts) {
    const o = opts || {};
    const bytes = utf8(text);
    let ver = o.version || 1;
    while (ver <= MAX_VERSION && 4 + (ver <= 9 ? 8 : 16) + bytes.length * 8 > dataCodewords(ver) * 8) {
      if (o.version) throw new Error("too long for version " + o.version);
      ver++;
    }
    if (ver > MAX_VERSION) throw new Error("too long for a QR code here");
    const size = ver * 4 + 17;
    const mod = Array.from({ length: size }, () => new Array(size).fill(false));
    const fn = Array.from({ length: size }, () => new Array(size).fill(false));
    const set = (x, y, dark) => { mod[y][x] = dark; fn[y][x] = true; };

    for (let i = 0; i < size; i++) { set(6, i, i % 2 === 0); set(i, 6, i % 2 === 0); }
    [[3, 3], [size - 4, 3], [3, size - 4]].forEach(([cx, cy]) => {
      for (let dy = -4; dy <= 4; dy++) {
        for (let dx = -4; dx <= 4; dx++) {
          const x = cx + dx;
          const y = cy + dy;
          if (x < 0 || x >= size || y < 0 || y >= size) continue;
          const d = Math.max(Math.abs(dx), Math.abs(dy));
          set(x, y, d !== 2 && d !== 4);
        }
      }
    });
    const pos = alignment(ver, size);
    pos.forEach((ay, i) => pos.forEach((ax, j) => {
      const last = pos.length - 1;
      if ((i === 0 && j === 0) || (i === 0 && j === last) || (i === last && j === 0)) return;
      for (let dy = -2; dy <= 2; dy++) {
        for (let dx = -2; dx <= 2; dx++) set(ax + dx, ay + dy, Math.max(Math.abs(dx), Math.abs(dy)) !== 1);
      }
    }));
    const drawFormat = (mask) => {
      const data = (FORMAT_BITS_M << 3) | mask;
      let rem = data;
      for (let i = 0; i < 10; i++) rem = (rem << 1) ^ ((rem >>> 9) * 0x537);
      const bits = ((data << 10) | rem) ^ 0x5412;
      const bit = (i) => ((bits >>> i) & 1) !== 0;
      for (let i = 0; i <= 5; i++) set(8, i, bit(i));
      set(8, 7, bit(6));
      set(8, 8, bit(7));
      set(7, 8, bit(8));
      for (let i = 9; i < 15; i++) set(14 - i, 8, bit(i));
      for (let i = 0; i < 8; i++) set(size - 1 - i, 8, bit(i));
      for (let i = 8; i < 15; i++) set(8, size - 15 + i, bit(i));
      set(8, size - 8, true);
    };
    drawFormat(0);
    if (ver >= 7) {
      let rem = ver;
      for (let i = 0; i < 12; i++) rem = (rem << 1) ^ ((rem >>> 11) * 0x1f25);
      const bits = (ver << 12) | rem;
      for (let i = 0; i < 18; i++) {
        const dark = ((bits >>> i) & 1) !== 0;
        const a = size - 11 + (i % 3);
        const b = Math.floor(i / 3);
        set(a, b, dark);
        set(b, a, dark);
      }
    }

    const words = interleaved(dataBits(bytes, ver), ver);
    let i = 0;
    for (let right = size - 1; right >= 1; right -= 2) {
      if (right === 6) right = 5;
      for (let vert = 0; vert < size; vert++) {
        for (let j = 0; j < 2; j++) {
          const x = right - j;
          const y = ((right + 1) & 2) === 0 ? size - 1 - vert : vert;
          if (!fn[y][x] && i < words.length * 8) {
            mod[y][x] = ((words[i >>> 3] >>> (7 - (i & 7))) & 1) !== 0;
            i++;
          }
        }
      }
    }

    const masked = (k) => {
      drawFormat(k);
      return mod.map((row, y) => row.map((dark, x) => (fn[y][x] ? dark : dark !== MASKS[k](x, y))));
    };
    if (o.mask !== undefined) return masked(o.mask);
    let best = null;
    let bestScore = Infinity;
    for (let k = 0; k < 8; k++) {
      const m = masked(k);
      const score = penalty(m);
      if (score < bestScore) { best = m; bestScore = score; }
    }
    return best;
  }

  // The code as an SVG, one path of unit squares, with the four-module
  // quiet zone; dark on light whatever the theme, as readers expect.
  function svg(text, px) {
    const m = matrix(text);
    const n = m.length + 8;
    const ns = "http://www.w3.org/2000/svg";
    const el = document.createElementNS(ns, "svg");
    el.setAttribute("viewBox", "0 0 " + n + " " + n);
    el.setAttribute("width", String(px));
    el.setAttribute("height", String(px));
    el.setAttribute("class", "qr");
    el.setAttribute("shape-rendering", "crispEdges");
    const ground = document.createElementNS(ns, "rect");
    ground.setAttribute("width", String(n));
    ground.setAttribute("height", String(n));
    ground.setAttribute("class", "qr-light");
    el.appendChild(ground);
    let d = "";
    m.forEach((row, y) => row.forEach((dark, x) => { if (dark) d += "M" + (x + 4) + " " + (y + 4) + "h1v1h-1z"; }));
    const path = document.createElementNS(ns, "path");
    path.setAttribute("d", d);
    path.setAttribute("class", "qr-dark");
    el.appendChild(path);
    return el;
  }

  M.qr = { matrix, svg };
})(window.Maity);
