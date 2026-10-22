{{- define "maity-hub.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "maity-hub.fullname" -}}
{{- if .Values.fullnameOverride -}}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{- define "maity-hub.selectorLabels" -}}
app.kubernetes.io/name: {{ include "maity-hub.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/*
Common labels. `app.kubernetes.io/version` is the image tag when one is set,
so it names what runs; with a digest it stays the chart's appVersion.
*/}}
{{- define "maity-hub.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "maity-hub.selectorLabels" . }}
app.kubernetes.io/version: {{ default .Chart.AppVersion .Values.image.tag | trunc 63 | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/*
The hub's own pods: the Deployment and the Service select on this, so the
migrate Job's and the test's pods, which share name and instance, are never
taken for the hub. A selector cannot change after the first install.
*/}}
{{- define "maity-hub.hubSelectorLabels" -}}
{{ include "maity-hub.selectorLabels" . }}
app.kubernetes.io/component: hub
{{- end -}}

{{- define "maity-hub.imagePullSecrets" -}}
{{- with .Values.imagePullSecrets }}
imagePullSecrets:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "maity-hub.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "maity-hub.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{- define "maity-hub.image" -}}
{{- $repository := required "image.repository is required: the hub image built from deploy/Dockerfile" .Values.image.repository -}}
{{- if .Values.image.digest -}}
{{- printf "%s@%s" $repository .Values.image.digest -}}
{{- else -}}
{{- printf "%s:%s" $repository (default .Chart.AppVersion .Values.image.tag) -}}
{{- end -}}
{{- end -}}

{{/*
MAITY_PUBLIC_URL: the explicit value, else https://<ingress.host>. A hub
without either would put http://localhost:8080 into every join link.
*/}}
{{- define "maity-hub.publicUrl" -}}
{{- if .Values.config.publicUrl -}}
{{- .Values.config.publicUrl | trimSuffix "/" -}}
{{- else if and .Values.ingress.enabled .Values.ingress.host -}}
{{- printf "https://%s" .Values.ingress.host -}}
{{- else -}}
{{- fail "config.publicUrl is required (or enable the Ingress with ingress.host): it is the address in every join link" -}}
{{- end -}}
{{- end -}}

{{/*
Refusals that would otherwise surface only at the first login. An Ingress
without trusted proxies leaves the hub seeing plain HTTP and one client
address, the controller's: logins and joins are refused, or every client
shares one rate-limit bucket. Plain HTTP is for a hub nothing outside the
cluster reaches, so it is refused with an Ingress or a Service that leaves
the cluster.
*/}}
{{- define "maity-hub.validate" -}}
{{- if .Values.ingress.enabled -}}
{{- if not .Values.ingress.host -}}
{{- fail "ingress.host is required with the Ingress enabled" -}}
{{- end -}}
{{- if not .Values.config.trustedProxies -}}
{{- fail "config.trustedProxies is required with the Ingress enabled: the ingress controller's pod network, so the hub believes its X-Forwarded-For and X-Forwarded-Proto" -}}
{{- end -}}
{{- end -}}
{{- if and .Values.config.allowPlainHttp (or .Values.ingress.enabled (ne .Values.service.type "ClusterIP")) -}}
{{- fail "config.allowPlainHttp is only for a hub nothing outside the cluster reaches: not with the Ingress enabled or a NodePort/LoadBalancer Service" -}}
{{- end -}}
{{- end -}}

{{/*
The environment the hub and the migrate Job share. The database URL and the
forge token come from Secrets by reference; their values never pass through
the chart.
*/}}
{{- define "maity-hub.env" -}}
- name: MAITY_DATABASE_URL
  valueFrom:
    secretKeyRef:
      name: {{ required "database.existingSecret is required: a Secret holding MAITY_DATABASE_URL" .Values.database.existingSecret }}
      key: {{ .Values.database.key }}
{{- with .Values.forge.github.existingSecret }}
- name: MAITY_FORGE_GITHUB_TOKEN
  valueFrom:
    secretKeyRef:
      name: {{ . }}
      key: {{ $.Values.forge.github.key }}
{{- end }}
- name: MAITY_PUBLIC_URL
  value: {{ include "maity-hub.publicUrl" . | quote }}
{{- if and .Values.ingress.enabled .Values.ingress.joinHost }}
- name: MAITY_JOIN_URL
  value: {{ printf "https://%s" .Values.ingress.joinHost | quote }}
{{- end }}
{{- with .Values.config.trustedProxies }}
- name: MAITY_TRUSTED_PROXIES
  value: {{ . | quote }}
{{- end }}
- name: MAITY_ALLOW_PLAIN_HTTP
  value: {{ ternary "1" "0" .Values.config.allowPlainHttp | quote }}
{{- if not .Values.config.dashboard }}
- name: MAITY_WEB_DIR
  value: ""
{{- end }}
{{- with .Values.extraEnv }}
{{ toYaml . }}
{{- end }}
{{- end -}}

{{- define "maity-hub.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "maity-hub.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}
