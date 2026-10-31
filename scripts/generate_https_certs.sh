#!/usr/bin/env bash
# Generate self-signed HTTPS certs for local JARVIS (cert.pem + key.pem).
# Same openssl invocation as README / CLAUDE.md. Idempotent with --force.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CERT="$ROOT/cert.pem"
KEY="$ROOT/key.pem"
FORCE=0

for arg in "$@"; do
  case "$arg" in
    -f|--force) FORCE=1 ;;
    -h|--help)
      echo "Usage: $0 [--force]"
      echo "Writes $CERT and $KEY (self-signed, CN=localhost, 365 days)."
      exit 0
      ;;
    *)
      echo "Unknown option: $arg" >&2
      exit 2
      ;;
  esac
done

if [[ -f "$CERT" && -f "$KEY" && "$FORCE" -ne 1 ]]; then
  echo "Already present (use --force to overwrite):"
  echo "  $CERT"
  echo "  $KEY"
  exit 0
fi

openssl req -x509 -newkey rsa:2048 \
  -keyout "$KEY" -out "$CERT" \
  -days 365 -nodes -subj '/CN=localhost'

chmod 600 "$KEY"
echo "Wrote:"
echo "  $CERT"
echo "  $KEY"
