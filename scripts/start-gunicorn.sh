#!/bin/sh
set -eu

: "${GUNICORN_WORKERS:=1}"
: "${GUNICORN_THREADS:=8}"
: "${GUNICORN_TIMEOUT:=120}"
: "${GUNICORN_BIND:=0.0.0.0:5000}"
: "${GUNICORN_ACCESS_LOGFILE:=-}"

require_positive_int() {
  name="$1"
  value="$2"
  case "$value" in
    ''|*[!0-9]*)
      echo "$name must be a positive integer, got: $value" >&2
      exit 1
      ;;
  esac
  if [ "$value" -lt 1 ]; then
    echo "$name must be a positive integer, got: $value" >&2
    exit 1
  fi
}

require_positive_int GUNICORN_WORKERS "$GUNICORN_WORKERS"
require_positive_int GUNICORN_THREADS "$GUNICORN_THREADS"
require_positive_int GUNICORN_TIMEOUT "$GUNICORN_TIMEOUT"

# Keep the default to one worker so the in-process scheduler is not duplicated.
# Threads let sync endpoints such as wait-message share the worker instead of
# blocking the entire site while waiting on upstream mail providers.
exec gunicorn \
  -w "$GUNICORN_WORKERS" \
  --threads "$GUNICORN_THREADS" \
  -b "$GUNICORN_BIND" \
  --timeout "$GUNICORN_TIMEOUT" \
  --access-logfile "$GUNICORN_ACCESS_LOGFILE" \
  web_outlook_app:app
