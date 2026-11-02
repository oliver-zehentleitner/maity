// The request signature (docs/api.md §2.2). The two hash functions are passed in, so that
// `tests/test_loadtest.py` checks this file against the hub without k6 and `run.js` uses k6's.

const encode = (text) =>
  encodeURIComponent(text).replace(/[!'()*]/g, (c) => `%${c.charCodeAt(0).toString(16).toUpperCase()}`);

export function canonicalQuery(pairs) {
  const encoded = pairs.map(([k, v]) => [encode(k), encode(v)]);
  const stable = encoded.map((pair, i) => [pair, i]);
  stable.sort((a, b) => (a[0][0] < b[0][0] ? -1 : a[0][0] > b[0][0] ? 1 : a[1] - b[1]));
  return stable.map(([[k, v]]) => `${k}=${v}`).join("&");
}

export function canonicalString(method, path, query, timestamp, nonce, body, sha256Hex) {
  return ["MAITY-HMAC-V1", method.toUpperCase(), path, query, timestamp, nonce, sha256Hex(body)].join("\n");
}

export function signedHeaders(account, method, path, pairs, body, now, nonce, hash) {
  const timestamp = String(now);
  const canonical = canonicalString(method, path, canonicalQuery(pairs), timestamp, nonce, body, hash.sha256Hex);
  return {
    Authorization: `Maity-HMAC ${account.credential_id}`,
    "Maity-Timestamp": timestamp,
    "Maity-Nonce": nonce,
    "Maity-Signature": hash.hmacHex(account.verifier, canonical),
  };
}
