#!/usr/bin/env bash
# Self-check for the ghl.sh vault and auto-lock, on a throwaway vault. Run: bash test_vault.sh
set -euo pipefail
T="$(mktemp -d)"; trap 'rm -rf "$T"' EXIT
source "$(dirname "$0")/ghl.sh" >/dev/null
ACCOUNTS_DIR="$T/accounts"; VAULT="$ACCOUNTS_DIR/vault.kdbx"; RAM="$T/ram"; mkdir -p "$ACCOUNTS_DIR"
ask_pw() { echo x >> "$T/asked"; echo testpw; }
systemd-run() { :; }; systemctl() { :; }   # never touch the real lock timer
asked() { wc -l < "$T/asked" 2>/dev/null || echo 0; }
fail() { echo "FAIL: $1"; exit 1; }

printf 'tok-a1' | cmd_vault_add a1 2>/dev/null;  [[ -f "$VAULT" ]] || fail "vault-add did not create the vault"
printf 'tok-a2' | cmd_vault_add a2 2>/dev/null
LOCK_MINUTES=60; rm -f "$T/asked"
[[ "$(ACCOUNT=a1; read_refresh 2>/dev/null)" == tok-a1 ]] || fail "locked read did not unlock"
[[ "$(asked)" == 1 ]] || fail "expected one password prompt"
[[ "$(ACCOUNT=a2; read_refresh)" == tok-a2 && "$(asked)" == 1 ]] || fail "asked again while unlocked"

echo 1 > "$RAM/.expires"                                     # lock time passed
echo tok-a1-new > "$RAM/a1"; : > "$RAM/a1.rotated"           # Firebase rotated a1 meanwhile
( cmd_lock ) 2>/dev/null && fail "lock wiped an unsaved rotated token"
[[ "$(ACCOUNT=a1; read_refresh 2>/dev/null)" == tok-a1-new ]] || fail "expired read did not unlock"
[[ "$(asked)" == 2 && ! -e "$RAM/a1.rotated" ]] || fail "rotated token not saved at relock"

cmd_lock 2>/dev/null; [[ ! -e "$RAM" ]] || fail "lock"
LOCK_MINUTES=0; cmd_unlock 2>/dev/null
(( $(cat "$RAM/.expires") > $(date +%s) + 10**9 )) || fail "lock_minutes=0 should mean until reboot"
echo "vault self-check passed"
