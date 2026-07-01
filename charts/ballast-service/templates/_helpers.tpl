{{- define "ballast-service.name" -}}
{{- default .Release.Name .Values.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{- define "ballast-service.labels" -}}
app: {{ include "ballast-service.name" . }}
app.kubernetes.io/name: {{ include "ballast-service.name" . }}
app.kubernetes.io/part-of: k8s-ballast
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{- define "ballast-service.selectorLabels" -}}
app: {{ include "ballast-service.name" . }}
{{- end -}}
