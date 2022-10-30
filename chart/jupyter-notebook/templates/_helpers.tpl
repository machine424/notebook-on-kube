{{/*
Name for resources created by the Release
*/}}
{{- define "jupyter-notebook.fullname" -}}
{{- .Release.Name }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "jupyter-notebook.labels" -}}
{{ include "jupyter-notebook.selectorLabels" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "jupyter-notebook.selectorLabels" -}}
app.kubernetes.io/name: {{ .Chart.Name }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}
