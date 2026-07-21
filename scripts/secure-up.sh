#!/usr/bin/env bash
# Start the stack from the ENCRYPTED secrets: decrypt -> start -> wipe the plaintext.
# The plaintext .env exists only for the seconds docker compose needs to read it;
# the running containers keep the values in memory. At rest only .env.enc remains.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env.enc ] || { echo "No .env.enc - run ./scripts/encrypt-env.sh first"; exit 1; }
cleanup() {
  if [ -f .env ]; then
    command -v shred >/dev/null 2>&1 && shred -u .env 2>/dev/null || rm -f .env
  fi
}
trap cleanup EXIT INT TERM
umask 077
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -in .env.enc -out .env
chmod 600 .env
docker compose up -d "$@"
echo "✓ started - plaintext .env wiped again (only .env.enc remains on disk)."
