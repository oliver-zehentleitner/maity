// Which addresses the load test may reach. Apart from `run.js` so that `tests/test_loadtest.py`
// checks it without k6. A plain origin only: userinfo or a path could make the host a reader sees
// differ from the host that is reached. A host under maity.team may be production: only
// LOADTEST_CONFIRMED_PRODUCTION names one, and `run.js` then takes it as the only target.
const ORIGIN = /^https?:\/\/((?:[a-z0-9-]+\.)*[a-z0-9-]+)(?::\d+)?$/i;

export function production(host) {
  return host === "maity.team" || host.endsWith(".maity.team");
}

export function hostOf(target) {
  const found = ORIGIN.exec(target);
  return found ? found[1].toLowerCase() : null;
}

export function refusal(target, confirmedList, confirmedProduction) {
  const host = hostOf(target);
  if (host === null) return `${target} is not a plain origin`;
  if (production(host)) {
    if (confirmedProduction !== host) {
      return `${host} may be production: LOADTEST_CONFIRMED_PRODUCTION does not name it`;
    }
    return null;
  }
  if (!confirmedList.split(",").filter(Boolean).includes(host)) {
    return `LOADTEST_CONFIRMED_TEST_SYSTEM does not name ${host}`;
  }
  return null;
}
