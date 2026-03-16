#!/usr/bin/env bash
# Setup age encryption for local .env secrets.
# Run once to generate a key and encrypt your existing .env file.
set -euo pipefail

AGE_KEY_DIR="${HOME}/.config/sops/age"
AGE_KEY_FILE="${AGE_KEY_DIR}/keys.txt"

# --- 1. Ensure age is installed ---
if ! command -v age &>/dev/null; then
    echo "Error: 'age' is not installed."
    echo "Install it with: sudo apt-get install -y age"
    exit 1
fi

# --- 2. Generate key if none exists ---
if [ -f "$AGE_KEY_FILE" ]; then
    echo "Age key already exists at ${AGE_KEY_FILE}"
else
    mkdir -p "$AGE_KEY_DIR"
    age-keygen -o "$AGE_KEY_FILE" 2>&1
    chmod 600 "$AGE_KEY_FILE"
    echo "Generated new age key at ${AGE_KEY_FILE}"
fi

# Extract public key
PUBLIC_KEY=$(grep -oP 'public key: \K.*' "$AGE_KEY_FILE")
echo "Public key: ${PUBLIC_KEY}"

# --- 3. Encrypt .env → .env.age ---
if [ ! -f .env ]; then
    echo "Error: No .env file found in current directory."
    echo "Create one from .env.example first: cp .env.example .env"
    exit 1
fi

age -r "$PUBLIC_KEY" -o .env.age .env
echo "Encrypted .env → .env.age"

# --- 4. Verify round-trip ---
DECRYPTED=$(age --decrypt --identity "$AGE_KEY_FILE" .env.age)
if diff <(cat .env) <(echo "$DECRYPTED") &>/dev/null; then
    echo "Round-trip verification: OK"
else
    echo "ERROR: Decrypted content does not match .env!"
    rm -f .env.age
    exit 1
fi

echo ""
echo "Done. You can now safely delete .env:"
echo "  rm .env"
echo ""
echo "To edit secrets later:"
echo "  age --decrypt --identity ${AGE_KEY_FILE} .env.age > .env.tmp"
echo "  # edit .env.tmp"
echo "  age -r ${PUBLIC_KEY} -o .env.age .env.tmp && rm .env.tmp"
