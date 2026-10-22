#!/usr/bin/env bash
# The chart without a cluster: lint, render every configuration in ci/, and
# make sure the refusals refuse. Needs helm 3.8+.
# Usage: deploy/helm/check.sh    exit 0 = all held
set -euo pipefail

chart="$(cd "$(dirname "$0")/maity-hub" && pwd)"
minimal="$chart/ci/minimal-values.yaml"
ingress="$chart/ci/ingress-values.yaml"
fails=0

ok() { printf 'ok   %s\n' "$1"; }
bad() { printf 'FAIL %s\n' "$1" >&2; fails=$((fails + 1)); }

for values in "$chart"/ci/*-values.yaml; do
    if helm lint --strict "$chart" -f "$values" >/dev/null; then
        ok "lint $(basename "$values")"
    else
        bad "lint $(basename "$values")"
    fi
done

render() { helm template t "$chart" "$@"; }

# What a rendered configuration must contain: one line per fact, matched literally.
expect() {
    local name="$1" out="$2"
    shift 2
    for line in "$@"; do
        if ! grep -qF -- "$line" <<<"$out"; then
            bad "$name: missing $line"
            return
        fi
    done
    ok "$name"
}

out="$(render -f "$minimal")"
expect "minimal: one pod, recreated, migrate hook first" "$out" \
    "replicas: 1" "type: Recreate" "helm.sh/hook: pre-install,pre-upgrade" 'args: ["migrate"]' \
    'value: "https://maity.example.org"' "image: maity-hub:ci" "readOnlyRootFilesystem: true"
grep -q "kind: Ingress" <<<"$out" && bad "minimal: an Ingress without ingress.enabled" || ok "minimal: no Ingress"
grep -q "MAITY_FORGE_GITHUB_TOKEN" <<<"$out" && bad "minimal: a token without a Secret" || ok "minimal: no forge token"
grep -q "MAITY_TRUSTED_PROXIES" <<<"$out" && bad "minimal: trusted proxies unset but rendered" || ok "minimal: no trusted proxies"

out="$(render -f "$ingress")"
expect "ingress: TLS host, defaults merged with the operator's annotation, digest, token" "$out" \
    "ingressClassName: nginx" "secretName: t-maity-hub-tls" 'value: "https://maity.example.org"' \
    'nginx.ingress.kubernetes.io/proxy-buffering: "off"' "cert-manager.io/cluster-issuer: letsencrypt" \
    "@sha256:0000000000000000000000000000000000000000000000000000000000000000" \
    "name: MAITY_FORGE_GITHUB_TOKEN" 'value: "10.244.0.0/16"'
grep -q "helm.sh/hook: pre-install" <<<"$out" && bad "ingress: migrate Job with migrate.enabled false" \
    || ok "ingress: no migrate Job when disabled"

out="$(render -f "$minimal" --set config.dashboard=false)"
expect "dashboard off: MAITY_WEB_DIR emptied" "$out" "name: MAITY_WEB_DIR"

# Each refusal: its name, the text the error must contain (any case: helm 3
# and 4 word schema errors differently), then the arguments.
refuse() {
    local name="$1" text="$2"
    shift 2
    local err
    if err="$(render "$@" 2>&1)"; then
        bad "$name: rendered"
    elif grep -qiF -- "$text" <<<"$err"; then
        ok "$name"
    else
        bad "$name: other error: $err"
    fi
}

refuse "no image" "image.repository is required" -f "$minimal" --set image.repository=
refuse "no database Secret" "database.existingSecret is required" -f "$minimal" --set database.existingSecret=
refuse "no public URL" "config.publicUrl is required" -f "$minimal" --set config.publicUrl=
refuse "Ingress without host" "ingress.host is required" -f "$minimal" --set ingress.enabled=true \
    --set config.trustedProxies=10.0.0.0/8
refuse "Ingress without trusted proxies" "config.trustedProxies is required" -f "$minimal" \
    --set ingress.enabled=true --set ingress.host=maity.example.org
refuse "a typo in a value" "additional propert" -f "$minimal" --set config.publicURL=https://x.example
refuse "a short digest" "match pattern" -f "$minimal" --set image.digest=sha256:abc
refuse "a replica count" "additional propert" -f "$minimal" --set replicaCount=2

if [ "$fails" -ne 0 ]; then
    printf '\nhelm check: %d failure(s)\n' "$fails" >&2
    exit 1
fi
printf '\nhelm check: all held\n'
