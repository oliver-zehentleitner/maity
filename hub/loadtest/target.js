// Which addresses the load test may reach. Apart from `run.js` so that `tests/test_loadtest.py`
// checks it without k6. A plain origin only: userinfo or a path could make the host a reader sees
// differ from the host that is reached.
const ORIGIN = /^https?:\/\/([a-z0-9.-]+)(?::\d+)?$/i;

export function refusal(target, confirmedList) {
  const found = ORIGIN.exec(target);
  if (!found) return `${target} is not a plain origin`;
  const host = found[1].toLowerCase().replace(/\.$/, "");
  if (host === "maity.team" || host.endsWith(".maity.team")) return `${host} may be production`;
  if (!confirmedList.split(",").filter(Boolean).includes(host)) {
    return `LOADTEST_CONFIRMED_TEST_SYSTEM does not name ${host}`;
  }
  return null;
}
