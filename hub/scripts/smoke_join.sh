#!/usr/bin/env bash
# End-to-end join, both paths a pasted line can take (docs/api.md §3), then one
# request from each agent to its human, answered and picked up (§7):
#   1. plain curl, exactly as the join page tells an agent with nothing installed;
#   2. the `maity` CLI: `maity join <url> --code <code>`, then `maity resume`.
# Runs a fresh hub on SQLite on loopback. Needs `maity-hub` and `maity` on PATH:
#   pip install -e hub -e cli   (one virtual environment is enough)
# Usage: hub/scripts/smoke_join.sh [port]    exit 0 = both paths worked
set -euo pipefail

port="${1:-18765}"
hub="http://127.0.0.1:${port}"
work="$(mktemp -d)"
server_pid=""
cleanup() {
    [ -n "$server_pid" ] && kill "$server_pid" 2>/dev/null || true
    rm -rf "$work"
}
trap cleanup EXIT

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
step() { printf '\n== %s\n' "$*"; }

export MAITY_DATABASE_URL="sqlite:///${work}/hub.db" MAITY_BIND="127.0.0.1:${port}"
export MAITY_PUBLIC_URL="$hub"
step "hub: migrate, owner, serve on $hub"
maity-hub migrate >/dev/null 2>&1
printf 'smoke owner password\n' | maity-hub owner create --handle owner --display-name Owner
maity-hub serve >"$work/serve.log" 2>&1 &
server_pid=$!
for _ in $(seq 50); do curl -sf "$hub/api/v1/health" >/dev/null && break; sleep 0.2; done

step "human: login, project, two join links"
jar="$work/cookies"
curl -sS --fail -c "$jar" -o /dev/null -H 'Content-Type: application/json' \
    -d '{"handle":"owner","password":"smoke owner password"}' "$hub/api/v1/auth/login"
csrf="$(curl -sS --fail -b "$jar" "$hub/api/v1/auth/session" | json 'd["csrf_token"]')"
human() { curl -sS --fail -b "$jar" -H "X-CSRF-Token: $csrf" -H 'Content-Type: application/json' "$@"; }
human -o /dev/null -d '{"slug":"smoke","name":"Smoke test"}' "$hub/api/v1/projects"
join_for() {
    human -d "{\"agent\":{\"handle\":\"$1\",\"display_name\":\"$1\"},\"role\":\"member\",\"areas\":[\"$1/\"]}" \
        "$hub/api/v1/projects/smoke/joins"
}
curl_join="$(join_for curl-agent)"
cli_join="$(join_for cli-agent)"

step "path 1: plain curl, as the join page says"
url="$(printf '%s' "$curl_join" | json 'd["join_url"]')"
code="$(printf '%s' "$curl_join" | json 'd["code"]')"
token="${url##*/}"
page="$(curl -sS --fail "$url")"
grep -q '^# Join Smoke test on Maity' <<<"$page"
grep -qF -- "$token" <<<"$page"
# The page never carries the code. (Not `! grep`: set -e ignores a negated command.)
if grep -qF -- "$code" <<<"$page"; then echo "smoke: the join page shows the code" >&2; exit 1; fi
git init -q "$work/clone-curl" && cd "$work/clone-curl"
d="$(git rev-parse --git-common-dir)/maity"
(umask 077; mkdir -p "$d"; curl -sS --fail -D "$work/exchange-headers" -o "$d/credential" \
    -X POST -H 'Content-Type: application/json' \
    -d "{\"code\":\"$code\",\"client\":\"curl\"}" "$hub/api/v1/join/$token")
grep -q '^HTTP/1.1 201' "$work/exchange-headers"
grep -qi '^Maity-Credential-Id: crd-' "$work/exchange-headers"
[ "$(stat -c %a "$d/credential")" = 600 ]
(umask 077; { printf '%s' 'header = "Authorization: Bearer '; cat "$d/credential"; printf '"\n'; } > "$d/curl.conf")
packet="$(curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' \
    -d '{"harness":"smoke","harness_version":"1","model":"none","client":"curl"}' \
    "$hub/api/v1/me/resume")"
printf '%s' "$packet" | json '"resumed as " + d["me"]["handle"] + ", session " + d["session"]["id"] + ", rules v" + str(d["rules"]["version"])'
curl -sS --fail "$hub/api/v1/help" | grep -q '^# Maity hub API'
again="$(curl -sS -o /dev/null -w '%{http_code}' -X POST -H 'Content-Type: application/json' \
    -d "{\"code\":\"$code\",\"client\":\"curl\"}" "$hub/api/v1/join/$token")"
[ "$again" = 404 ]   # single use

step "path 2: the maity CLI"
url="$(printf '%s' "$cli_join" | json 'd["join_url"]')"
code="$(printf '%s' "$cli_join" | json 'd["code"]')"
git init -q "$work/clone-cli" && cd "$work/clone-cli"
maity join "$url" --code "$code" --harness smoke --model none --no-pointer >"$work/cli-join.out" 2>&1
grep -q '^joined smoke as agt-' "$work/cli-join.out"
maity resume | json '"resumed as " + d["me"]["handle"] + ", session " + d["session"]["id"]'

step "requests: each agent asks its human, the human answers"
key() { python3 -c 'import uuid; print(uuid.uuid4())'; }
cd "$work/clone-curl"
d="$(git rev-parse --git-common-dir)/maity"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -H "Idempotency-Key: $(key)" \
    -d '{"class":"decision","title":"Which hash?","options":[{"id":"a","label":"A"},{"id":"b","label":"B"}]}' \
    "$hub/api/v1/projects/smoke/requests" | json '"curl agent asked " + d["id"] + " to " + d["to"]'
cd "$work/clone-cli"
maity ask "Tag 0.1.0 now?" --to human --class consent --option yes --option no
inbox="$(human -X GET "$hub/api/v1/requests")"
[ "$(printf '%s' "$inbox" | json 'len(d["items"])')" = 2 ]
for id in $(printf '%s' "$inbox" | json '" ".join(r["id"] for r in d["items"])'); do
    reply="$(printf '%s' "$inbox" | json "next(r['replies'][0]['id'] for r in d['items'] if r['id'] == '$id')")"
    human -o /dev/null -d "{\"reply_id\":\"$reply\"}" "$hub/api/v1/projects/smoke/requests/$id/answer"
done
maity resume | json '"cli agent got " + str(len(d["requests"]["answered_since_cursor"])) + " answer(s)"' \
    | tee "$work/cli-answers" && grep -q "got 1 answer" "$work/cli-answers"
cd "$work/clone-curl"
curl -sS --fail -K "$d/curl.conf" -X POST -H 'Content-Type: application/json' -d '{"client":"curl"}' \
    "$hub/api/v1/me/resume" | json '"curl agent got " + str(len(d["requests"]["answered_since_cursor"])) + " answer(s)"' \
    | tee "$work/curl-answers" && grep -q "got 1 answer" "$work/curl-answers"

step "human: both agents are members"
human "$hub/api/v1/projects/smoke/members" -X GET \
    | json '", ".join(m["handle"] + "/" + m["presence"] for m in d["items"])'
printf '\nsmoke: both join paths worked, and both agents got their answers\n'
