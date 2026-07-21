#!/usr/bin/env bash
# One-time: encrypt .env -> .env.enc (AES-256-CBC, PBKDF2 200k). You choose the passphrase.
# After verifying secure-up.sh works, DELETE the plaintext .env.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "No .env found in $(pwd)"; exit 1; }
umask 077
openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -in .env -out .env.enc
chmod 600 .env.enc
echo "✓ .env.enc written ($(wc -c < .env.enc) bytes)."
echo
echo "NEXT:"
echo "  1) Test the start:   ./scripts/secure-up.sh"
echo "  2) If it works, remove the plaintext:   shred -u .env   (or: rm -f .env)"
echo "  3) Keep the passphrase in your password manager - there is NO recovery."
