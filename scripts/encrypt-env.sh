#!/usr/bin/env bash
# One-time: encrypt .env -> .env.enc (AES-256-CBC, PBKDF2 200k). You choose the passphrase.
# After verifying secure-up.sh works, DELETE the plaintext .env.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "No .env found in $(pwd)"; exit 1; }
# See secure-up.sh: chmod is a no-op on NTFS, so lock the ACL down on Windows too.
lock_down() {
  chmod 600 "$1" 2>/dev/null || true
  if command -v icacls >/dev/null 2>&1; then
    icacls "$(cygpath -w "$1" 2>/dev/null || echo "$1")" \
      /inheritance:r /grant:r "$(whoami):(F)" >/dev/null 2>&1 || true
  fi
}

umask 077
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in .env -out .env.enc
lock_down .env.enc
echo "✓ .env.enc written ($(wc -c < .env.enc) bytes)."
echo
echo "NEXT:"
echo "  1) Test the start:   ./scripts/secure-up.sh"
echo "  2) If it works, remove the plaintext:   shred -u .env   (or: rm -f .env)"
echo "  3) Keep the passphrase in your password manager - there is NO recovery."
