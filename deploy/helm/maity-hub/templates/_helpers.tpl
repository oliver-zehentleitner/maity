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

{{- define "maity-hub.labels" -}}
helm.sh/chart: {{ printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{ include "maity-hub.selectorLabels" . }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
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
Refusals that would otherwise surface only at the first login: an Ingress
without trusted proxies leaves the hub seeing plain HTTP from the controller.
*/}}
{{- define "maity-hub.validate" -}}
{{- if .Values.ingress.enabled -}}
{{- if not .Values.ingress.host -}}
{{- fail "ingress.host is required with the Ingress enabled" -}}
{{- end -}}
{{- if and (not .Values.config.trustedProxies) (not .Values.config.allowPlainHttp) -}}
{{- fail "config.trustedProxies is required with the Ingress enabled: the ingress controller's pod network, so the hub believes its X-Forwarded-Proto" -}}
{{- end -}}
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
