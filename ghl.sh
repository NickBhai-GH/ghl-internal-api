#!/usr/bin/env bash
# GHL internal workflow API toolkit (multi-account).
#
# Layout:
#   accounts/vault.kdbx                  KeePassXC vault: one entry per account (title = account
#                                        name, password = long-lived Firebase refresh token).
#   accounts/lock_minutes                Optional, one number: minutes until the toolkit locks again
#                                        and asks for the vault password (default 60, 0 = until reboot).
#   $XDG_RUNTIME_DIR/ghl/<name>          Refresh token while unlocked. RAM only, wiped on lock/reboot.
#   accounts/<name>/token.txt            Short-lived idToken; auto-refreshed when <60s remain.
#   workflows/<location_id>/<wf>.json    Per-workflow dump output.
#   reports/<location_id>-triage.csv     Triage CSV output.
#
# Default account is read from accounts/default (one line, account name) or first dir found.
# Override per-call with `-a <account>`.
#
# Subcommands (reads unless marked WRITE):
#   unlock                    Ask for the vault password, load refresh tokens into RAM.
#   lock                      Wipe the tokens now (happens by itself after lock_minutes).
#   save                      Write rotated refresh tokens back into the vault.
#   vault-add <name>          Store an account's refresh token (stdin) in the vault; creates it if missing.
#   token-info                Token claims + expiry.
#   refresh                   Force-mint a new idToken.
#   parse-url <url>           Extract location_id and workflow_id from a GHL URL.
#   list <loc>                List all workflows in a location (id, name, status, updatedAt).
#   folders <loc>             List workflow folders (id, name, parentId).
#   get <loc> <wf>            Dump one workflow JSON.
#   summary <loc> <wf>        Pretty-print node list of a previously-dumped workflow.
#   dump-all <loc>            Dump every workflow in a location.
#   nodes <loc> <wf>          Live triggers + node list WITH copy snippets (follows Firebase fileUrl).
#   triage <loc>              Build CSV: name, status, currently_enrolled, node_count, updated.
#   enroll-stats <loc> <wf>.. Live enrollment counts for one or more workflows.
#   backup <loc> <wf> [label] Snapshot meta + body + triggers to backups/ before an edit.
#   meta-diff <meta.json> <loc> <wf>  Prove an edit changed only the node tree.
#   fields <loc> [model]      Custom fields (default model=contact).
#   calendars <loc>           Calendars: name/type/active/id.
#   pipelines <loc>           Pipelines + ordered stages.
#   forms <loc>               Forms: id/name/field-count.
#   dispositions <loc>        Custom call dispositions (workflow triggers match these by literal name).
#   contacts <loc>            Total contact count (cheap import-status check).
#   contacts-scan <loc> ...   Paginate ALL contacts + hydrate custom-field values.
#                             --list-fields | --where 'Name~sub'/'Name=val' | --select 'A,B'
#                             | --out f.json | --csv f.csv  (see contacts_scan.py -h)
#   numbers <loc>             Phone numbers owned by the location (forwarding target, default flag, RingAll users).
#   dialer <loc>              Dialer view: owned numbers + verified caller IDs + default-outbound mapping.
#   inbound <loc>             Raw Twilio inbound config (voice_url, status_callback, etc.).
#   raw <path> [version]      Authenticated GET of any internal-API path (begins with "/"), pretty-printed.
#   move <loc> <wf> <folder>  WRITE: move a workflow into a folder ("root" = top level).
#   post <path> <json|@file> [version]   WRITE: authenticated POST, prints the JSON response.
#   put  <path> <json|@file> [version]   WRITE: authenticated PUT (full payload, see ENDPOINTS.md).
#   del  <path> [version]                WRITE: authenticated DELETE.

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNTS_DIR="$DIR/accounts"
OUT_DIR="$DIR/workflows"
REPORT_DIR="$DIR/reports"
API="https://backend.leadconnectorhq.com"
ORIGIN="https://client-app-automation-workflows.leadconnectorhq.com"
FIREBASE_KEY="AIzaSyB_w3vXmsI7WeQtrIOkjR6xTRVN5uOieiE"
REFRESH_THRESHOLD=60
VAULT="$ACCOUNTS_DIR/vault.kdbx"
RAM="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/ghl"
LOCK_MINUTES="$(tr -d '\n\r ' 2>/dev/null < "$ACCOUNTS_DIR/lock_minutes" || true)"
[[ "$LOCK_MINUTES" =~ ^[0-9]+$ ]] || LOCK_MINUTES=60

ACCOUNT=""

resolve_account() {
  if [[ -n "$ACCOUNT" ]]; then
    echo "$ACCOUNT"
    return
  fi
  if [[ -f "$ACCOUNTS_DIR/default" ]]; then
    tr -d '\n\r ' < "$ACCOUNTS_DIR/default"
    return
  fi
  local d; for d in "$ACCOUNTS_DIR"/*/; do [[ -d "$d" ]] && basename "$d"; break; done
}

acct_dir() {
  local name; name="$(resolve_account)"
  [[ -z "$name" ]] && { echo "ERROR: no account configured. Add one with: ./ghl.sh vault-add <name>." >&2; exit 1; }
  echo "$ACCOUNTS_DIR/$name"
}

decode_payload() {
  local tok="$1" payload pad i
  payload="$(echo "$tok" | cut -d. -f2)"
  pad=$(( (4 - ${#payload} % 4) % 4 ))
  for ((i=0; i<pad; i++)); do payload+='='; done
  printf '%s' "$payload" | base64 -d 2>/dev/null
}

token_exp() { decode_payload "$1" | jq -r '.exp // 0'; }

# keepassxc-cli: native install, else the Flathub KeePassXC app.
kp() {
  if command -v keepassxc-cli >/dev/null; then keepassxc-cli "$@"
  else flatpak run --command=keepassxc-cli org.keepassxc.KeePassXC "$@"; fi
}

# Vault password: desktop popup (KDE or GNOME), terminal prompt otherwise. Printed to stdout for a pipe.
ask_pw() {
  if [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] && command -v kdialog >/dev/null; then
    kdialog --title "GHL toolkit" --password "$1"
  elif [[ -n "${WAYLAND_DISPLAY:-}${DISPLAY:-}" ]] && command -v zenity >/dev/null; then
    zenity --password --title "GHL toolkit: $1"
  else
    local p; read -rsp "$1: " p </dev/tty; echo >&2; printf '%s\n' "$p"
  fi
}

# Unlocked = tokens in RAM and the lock time not reached yet. When not, ask for the password now.
is_unlocked() { [[ -d "$RAM" ]] && (( $(cat "$RAM/.expires" 2>/dev/null || echo 0) > $(date +%s) )); }
ensure_unlocked() { is_unlocked || cmd_unlock; }

read_refresh() {
  ensure_unlocked
  local f; f="$RAM/$(resolve_account)"
  [[ -s "$f" ]] || { echo "ERROR: no '$(resolve_account)' entry in the vault. Add it: ./ghl.sh vault-add $(resolve_account)" >&2; exit 6; }
  tr -d '\n\r ' < "$f"
}

# Store one token in the vault (edit if the entry exists, add if not).
vault_put() {
  local name="$1" tok="$2" pw="$3" act=add
  printf '%s\n' "$pw" | kp show -q "$VAULT" "$name" >/dev/null 2>&1 && act=edit
  printf '%s\n%s\n' "$pw" "$tok" | kp "$act" -q -p "$VAULT" "$name" >/dev/null
}

# Write tokens Firebase rotated while unlocked back into the vault, so they survive the lock.
save_rotated() {
  local f name
  for f in "$RAM"/*.rotated; do
    [[ -e "$f" ]] || continue
    name="$(basename "$f" .rotated)"
    vault_put "$name" "$(tr -d '\n\r ' < "$RAM/$name")" "$1" || { echo "ERROR: could not save $name (wrong password?)." >&2; exit 1; }
    rm -f "$f"; echo "Saved rotated token for $name." >&2
  done
}

cmd_unlock() {
  [[ -f "$VAULT" ]] || { echo "ERROR: no vault at $VAULT. Add an account first: ./ghl.sh vault-add <name>" >&2; exit 1; }
  local pw csv exp
  pw="$(ask_pw "KeePassXC vault password")" || { echo "Cancelled." >&2; exit 1; }
  save_rotated "$pw"
  csv="$(printf '%s\n' "$pw" | kp export -q -f csv "$VAULT")" || { echo "ERROR: wrong vault password." >&2; exit 1; }
  rm -rf "$RAM"; (umask 077; mkdir -p "$RAM")
  printf '%s' "$csv" | python3 -I -c '
import csv, re, sys, os
n = 0
for r in csv.DictReader(sys.stdin):
    if re.fullmatch(r"[A-Za-z0-9_-]+", r["Title"]) and r["Password"]:
        with open(os.path.join(sys.argv[1], r["Title"]), "w") as f: f.write(r["Password"] + "\n")
        n += 1
print(f"Unlocked {n} accounts", end=" ", file=sys.stderr)' "$RAM"
  if (( LOCK_MINUTES )); then
    exp=$(( $(date +%s) + LOCK_MINUTES * 60 )); echo "for $LOCK_MINUTES minutes." >&2
    # Wipe the tokens at the lock time even if nothing runs. ponytail: needs systemd --user;
    # without it the lock only kicks in on the next ghl.sh call (the .expires check above).
    if command -v systemd-run >/dev/null; then
      systemctl --user stop ghl-autolock.timer >/dev/null 2>&1 || true
      systemd-run --user -q --collect --unit=ghl-autolock --on-active="${LOCK_MINUTES}m" "$DIR/ghl.sh" lock >/dev/null 2>&1 || true
    fi
  else
    exp=99999999999; echo "until reboot." >&2
  fi
  echo "$exp" > "$RAM/.expires"
}

# Refuses while rotated tokens are unsaved (they would be lost); the next unlock saves them.
cmd_lock() {
  compgen -G "$RAM/*.rotated" >/dev/null && { echo "ERROR: unsaved rotated tokens. Run ./ghl.sh save first." >&2; exit 1; }
  rm -rf "$RAM" "$ACCOUNTS_DIR"/*/token.txt
  echo "Locked." >&2
}

cmd_save() {
  local pw
  compgen -G "$RAM/*.rotated" >/dev/null || { echo "Nothing to save." >&2; return; }
  pw="$(ask_pw "KeePassXC vault password (saving rotated tokens)")" || exit 1
  save_rotated "$pw"
}

cmd_vault_add() {
  local name="${1:?usage: printf %s TOKEN | ./ghl.sh vault-add <name>}" tok pw pw2
  [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || { echo "ERROR: bad account name." >&2; exit 1; }
  tok="$(tr -d '\n\r ')"; [[ -n "$tok" ]] || { echo "ERROR: no token on stdin." >&2; exit 1; }
  if [[ ! -f "$VAULT" ]]; then
    pw="$(ask_pw "New vault password")" || exit 1
    pw2="$(ask_pw "Repeat new vault password")" || exit 1
    [[ -n "$pw" && "$pw" == "$pw2" ]] || { echo "ERROR: passwords empty or different." >&2; exit 1; }
    printf '%s\n%s\n' "$pw" "$pw" | kp db-create -q -p "$VAULT" >/dev/null || { echo "ERROR: could not create $VAULT." >&2; exit 1; }
    echo "Created $VAULT." >&2
  else
    pw="$(ask_pw "KeePassXC vault password (adding $name)")" || exit 1
  fi
  vault_put "$name" "$tok" "$pw" || { echo "ERROR: vault write failed (wrong password?)." >&2; exit 1; }
  (umask 077; mkdir -p "$ACCOUNTS_DIR/$name"; [[ -d "$RAM" ]] && printf '%s\n' "$tok" > "$RAM/$name" || true)
  echo "Added $name to the vault." >&2
}

do_refresh() {
  local refresh resp new_id new_refresh tf rf
  tf="$(acct_dir)/token.txt"
  rf="$RAM/$(resolve_account)"
  refresh="$(read_refresh)"
  resp="$(curl -sS -X POST "https://securetoken.googleapis.com/v1/token?key=$FIREBASE_KEY" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "grant_type=refresh_token" \
    --data-urlencode "refresh_token=$refresh")"
  new_id="$(echo "$resp" | jq -r '.id_token // empty')"
  new_refresh="$(echo "$resp" | jq -r '.refresh_token // empty')"
  if [[ -z "$new_id" ]]; then
    echo "ERROR: Firebase refresh failed [$(resolve_account)]:" >&2
    echo "$resp" >&2
    exit 5
  fi
  printf '%s\n' "$new_id" > "$tf"; chmod 600 "$tf"
  if [[ -n "$new_refresh" && "$new_refresh" != "$refresh" ]]; then
    printf '%s\n' "$new_refresh" > "$rf"; chmod 600 "$rf"; : > "$rf.rotated"
    echo "WARNING: refresh_token rotated for $(resolve_account). Run ./ghl.sh save (or it is saved at the next unlock)." >&2
  fi
}

ensure_fresh_token() {
  local tf exp now_ts
  tf="$(acct_dir)/token.txt"
  if [[ ! -s "$tf" ]]; then do_refresh; return; fi
  exp="$(token_exp "$(tr -d '\n\r ' < "$tf")" 2>/dev/null || echo 0)"
  now_ts="$(date +%s)"
  (( exp - now_ts < REFRESH_THRESHOLD )) && do_refresh
}

read_token() {
  ensure_unlocked
  ensure_fresh_token
  tr -d '\n\r ' < "$(acct_dir)/token.txt"
}

# Common header set used by every authenticated call.
auth_headers() {
  local tok; tok="$(read_token)"
  printf -- '-H\ntoken-id: %s\n-H\nchannel: APP\n-H\nversion: 2021-04-15\n-H\nsource: WEB_USER\n-H\norigin: %s\n-H\naccept: application/json, text/plain, */*\n' "$tok" "$ORIGIN"
}

# ----- subcommands -----

cmd_token_info() {
  local tok payload now_ts
  tok="$(read_token)"
  payload="$(decode_payload "$tok")"
  now_ts="$(date +%s)"
  echo "$payload" | jq --argjson now "$now_ts" --arg acct "$(resolve_account)" '{
    account: $acct, user_id, company_id, role, type,
    issued: (.iat | todate),
    expires: (.exp | todate),
    seconds_remaining: (.exp - $now),
    locations_in_jwt: (.locations | length),
    location_ids: .locations
  }'
}

cmd_refresh() { do_refresh; cmd_token_info; }

cmd_parse_url() {
  local url="$1" loc wf
  loc="$(echo "$url" | grep -oE 'location/[A-Za-z0-9]+' | head -1 | cut -d/ -f2)"
  wf="$(echo "$url" | grep -oE 'workflow/[A-Za-z0-9-]+' | head -1 | cut -d/ -f2)"
  printf 'LOCATION_ID=%s\nWORKFLOW_ID=%s\n' "$loc" "$wf"
}

cmd_list() {
  local loc="$1" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflows/?locationId=$loc" \
  | jq '.workflows | sort_by(.name)'
}

cmd_get() {
  local loc="$1" wf="$2" tok dest code base trig
  tok="$(read_token)"
  mkdir -p "$OUT_DIR/$loc"
  dest="$OUT_DIR/$loc/$wf.json"
  base="$dest.base"
  trig="$dest.trig"
  # ?includeScheduledPauseInfo=true returns the full workflow doc (name, status, workflowData, ...).
  # ?includeTriggers=true returns a slim doc with .triggers (and re-emits workflowData/permissionMeta).
  # Fetch both and merge so the dump has metadata + workflow body + triggers.
  code="$(curl -sS -w '%{http_code}' -o "$base" \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflow/$loc/$wf?includeScheduledPauseInfo=true")"
  if [[ "$code" != "200" ]]; then
    echo "ERROR: HTTP $code on $wf (base)" >&2; cat "$base" >&2; rm -f "$base"; return 3
  fi
  code="$(curl -sS -w '%{http_code}' -o "$trig" \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflow/$loc/$wf?includeTriggers=true")"
  if [[ "$code" != "200" ]]; then
    echo "WARN: HTTP $code fetching triggers for $wf" >&2
    jq . "$base" > "$dest"
  else
    jq -s '.[0] + {triggers: (.[1].triggers // [])}' "$base" "$trig" > "$dest"
  fi
  rm -f "$base" "$trig"
  echo "saved -> $dest ($(wc -c < "$dest") bytes)"
}

cmd_summary() {
  local loc="$1" wf="$2" f="$OUT_DIR/$loc/$wf.json"
  [[ -f "$f" ]] || { echo "no dump at $f. run: $0 get $loc $wf" >&2; exit 4; }
  jq '{
    name, status, type, version, dataVersion, updatedAt,
    node_count: (.workflowData.templates | length),
    nodes: [.workflowData.templates[] | {order, type, name, id}],
    trigger_count: (.triggers // [] | length),
    triggers: [(.triggers // [])[] | {name, type, active, conditions}]
  }' "$f"
}

cmd_dump_all() {
  local loc="$1" tok ids count i wf
  tok="$(read_token)"
  ids=$(curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflows/?locationId=$loc" | jq -r '.workflows[].id')
  count=$(echo "$ids" | wc -l)
  echo "dumping $count workflows for location $loc..." >&2
  i=0
  for wf in $ids; do
    i=$((i+1))
    printf '[%3d/%d] ' "$i" "$count" >&2
    cmd_get "$loc" "$wf" || true
  done
}

cmd_triage() {
  local loc="$1" tok
  tok="$(read_token)"
  python3 "$DIR/triage.py" "$loc" "$tok"
}

cmd_folders() {
  local loc="$1" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflow/$loc/list?limit=500&offset=0&sortBy=name&sortOrder=asc" \
  | jq '[.rows[] | select(.type=="directory") | {id: ._id, name, parentId}]'
}

# move <loc> <wf_id> <folder_id> : move a workflow into a folder (parentId).
# Empty/"root" folder_id moves it back to the top level.
cmd_move() {
  local loc="$1" wf="$2" folder="${3:-}" tok pid
  tok="$(read_token)"
  [[ "$folder" == "root" ]] && folder=""
  pid="$( [[ -n "$folder" ]] && printf '"%s"' "$folder" || printf 'null' )"
  curl -sS -w '\nHTTP %{http_code}\n' -X PUT \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'content-type: application/json' \
    -H 'accept: application/json, text/plain, */*' \
    "$API/workflow/$loc/move-directory/$wf" \
    --data-raw "{\"parentId\":$pid}"
}

cmd_numbers() {
  local loc="$1" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/phone-system/numbers/v2/location/$loc?pageSize=100&page=0&searchFilter=" \
  | jq '{total, numbers: [.numbers[] | {phoneNumber, friendlyName, isDefaultNumber, forwardingNumber, linkedRingAllUsers, isGroupConversationEnabled, sid, type, capabilities}]}'
}

cmd_dialer() {
  local loc="$1" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/phone-system/numbers/location/$loc/dialer?pageSize=100&page=0&showVerifiedCallerIds=true" \
  | jq '{
      defaultOutbound: .defaultOutboundNumber.phoneNumber,
      defaultOutboundName: .defaultOutboundNumber.friendlyName,
      defaultOutboundType,
      numberNameMapping,
      regionToNumberMapping,
      regionToCallerIdNumberMapping,
      numbers: [.numbers[] | {phoneNumber, friendlyName, userFullName, isCallerIdVerified, isDefaultNumber, isCallRecordingEnabled, type}]
    }'
}

cmd_inbound() {
  local loc="$1" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/phone-system/numbers/inbound?locationId=$loc&skipNumberPool=true" \
  | jq '{accountStatus, incoming_phone_numbers: [.incoming_phone_numbers[] | {phone_number, friendly_name, status, voice_url, voice_method, status_callback, sid, date_created, date_updated}]}'
}

cmd_enroll_stats() {
  local loc="$1" tok qs
  shift
  tok="$(read_token)"
  qs=""
  for wf in "$@"; do qs="${qs}workflowIds[]=${wf}&"; done
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    "$API/workflows/status/search/enroll-stats-cache?${qs}locationId=$loc"
}

# ---- generic authenticated reads (added 2026-06-29) ----------------------
# gget <path> [version] : authenticated GET against $API. <path> begins with "/".
# Real browser UA avoids the Cloudflare 1010 trap; curl alone is safe but keep it explicit.
gget() {
  local path="$1" ver="${2:-2021-04-15}" tok
  tok="$(read_token)"
  curl -sS \
    -H "token-id: $tok" -H 'channel: APP' -H "version: $ver" -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'accept: application/json, text/plain, */*' \
    -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' \
    "$API$path"
}

# raw <path> [version] : dump arbitrary internal-API GET, pretty-printed.
# ---- generic authenticated write helpers (added 2026-09-01) ----
# gwrite <METHOD> <path> <json_body> [version]
gwrite() {
  local method="$1" path="$2" body="$3" ver="${4:-2021-04-15}" tok
  tok="$(read_token)"
  curl -sS -X "$method" \
    -H "token-id: $tok" -H 'channel: APP' -H "version: $ver" -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'content-type: application/json' \
    -H 'accept: application/json, text/plain, */*' \
    -H 'user-agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36' \
    "$API$path" --data-raw "$body"
}
gpost() { gwrite POST "$@"; }
gput()  { gwrite PUT  "$@"; }

# post|put <path> <json-or-@file> [version] / del <path> [version] : raw writes, print the JSON
# response. Back up first and send FULL payloads on PUT (see AGENTS.md safety contract).
cmd_del()  { gwrite DELETE "$1" "" "${2:-}" | jq . ; }
cmd_post() { local b="$2"; [[ "$b" == @* ]] && b="$(cat "${b#@}")"; gpost "$1" "$b" "${3:-}" | jq . ; }
cmd_put()  { local b="$2"; [[ "$b" == @* ]] && b="$(cat "${b#@}")"; gput  "$1" "$b" "${3:-}" | jq . ; }

cmd_raw() { gget "$1" "${2:-}" | jq . ; }

# dispositions <loc> : the Custom Disposition list (the buttons an SDR clicks after
# a call). NOT under the normal settings API — it lives on /phone-system/. There is
# no other read path for it, and workflow triggers match these by LITERAL NAME, so
# a rename silently kills every trigger pointing at the old string.
cmd_dispositions() {
  gget "/phone-system/call-dispositions?locationId=$1" \
    | jq -r '.dispositions | "count: \(length)",
             (sort_by(.orderingKey)[] | "  [\(.name)]  created \(.createdAt)")'
}

# backup <loc> <wf> [label] : snapshot meta + real node body + triggers before you
# edit a LIVE workflow. Always run this first — a body PUT clobbers every field you
# omit (status, allowMultiple, ...), and this is what you diff against afterwards.
cmd_backup() {
  local loc="$1" wf="$2" label="${3:-backup}" stamp dest meta url
  stamp="$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$DIR/backups"
  dest="$DIR/backups/${label}_${wf:0:8}_${stamp}"
  meta="$(gget "/workflow/$loc/$wf?includeScheduledPauseInfo=true")"
  echo "$meta" > "${dest}_meta.json"
  url="$(echo "$meta" | jq -r '.fileUrl // empty')"
  [[ -n "$url" ]] && curl -sS "$url" > "${dest}_body.json"
  gget "/workflow/$loc/$wf?includeTriggers=true" | jq '.triggers' > "${dest}_triggers.json"
  echo "$meta" | jq -r '"backed up: \(.name)  v\(.version)  status=\(.status // "draft")"'
  echo "  -> ${dest}_{meta,body,triggers}.json"
}

# meta-diff <backup_meta.json> <loc> <wf> : prove a body PUT changed ONLY the nodes.
# Catches the silent clobbers (status -> draft, allowMultiple -> false, note wiped).
cmd_meta_diff() {
  local old="$1" loc="$2" wf="$3"
  gget "/workflow/$loc/$wf?includeScheduledPauseInfo=true" \
  | jq -s --slurpfile o "$old" '
      ($o[0]) as $old | .[0] as $new
      | ["workflowData","fileUrl","filePath","updatedAt","version",
         "permissionMeta","__v","updatedBy","meta","triggersFilePath"] as $skip
      | [ (($old|keys) + ($new|keys) | unique)[]
          | select(. as $k | $skip | index($k) | not)
          | select($old[.] != $new[.])
          | "  \(.): \($old[.]|tostring) -> \($new[.]|tostring)" ]
      | if length == 0 then "meta clean: only the node tree changed"
        else "SETTINGS CHANGED (restore these):\n" + join("\n") end' -r
}

# nodes <loc> <wf> : the one I keep rebuilding. Fetches workflow meta, follows
# fileUrl (Firebase) for the real node body, prints triggers + node list w/ copy snippets.
cmd_nodes() {
  local loc="$1" wf="$2" meta fileurl
  meta="$(gget "/workflow/$loc/$wf?includeScheduledPauseInfo=true")"
  echo "$meta" | jq -r '"name: \(.name)\nstatus: \(.status // "draft")\nnode_count(meta): \(.workflowData.templates|length // 0)"'
  echo "triggers:"
  gget "/workflow/$loc/$wf?includeTriggers=true" | jq -r '(.triggers // [])[] | "  - \(.name // .type)"'
  fileurl="$(echo "$meta" | jq -r '.fileUrl // empty')"
  [[ -z "$fileurl" ]] && { echo "(no fileUrl; body inline above)"; return; }
  echo "nodes:"
  curl -sS "$fileurl" | jq -r '
    .templates[] |
    "  - \(.type) | \(.name)" +
    (((.attributes.message // .attributes.body // .attributes.html // "") | tostring | gsub("\\s+";" ") | .[0:60]) as $c
      | if ($c|length)>0 then " | " + $c else "" end)'
}

# fields <loc> [model] : custom fields (default contact model).
cmd_fields() {
  gget "/locations/$1/customFields?model=${2:-contact}" \
    | jq -r '(.customFields // .customField // [])[] | "  - \(.name) | \(.dataType)"'
}

# calendars <loc> : id/name/type/active.
cmd_calendars() {
  gget "/calendars/?locationId=$1&showThirdParty=false" \
    | jq -r '.calendars[] | "  - \(.name) | type:\(.calendarType) active:\(.isActive) id:\(.id)"'
}

# pipelines <loc> : name + ordered stage list.
cmd_pipelines() {
  gget "/opportunities/pipelines?locationId=$1" \
    | jq -r '.pipelines[] | "  - \(.name)\n      stages: " + ([.stages[].name] | join(" > "))'
}

# forms <loc> : id/name/field-count.
cmd_forms() {
  gget "/forms/?locationId=$1&limit=100" \
    | jq -r '.forms[] | "  - \(.name) | id:\(._id // .id) | fields:\((.formFields // .fields // [])|length)"'
}

# contacts <loc> : total contact count (cheap import-status check).
cmd_contacts() {
  gget "/contacts/search/duplicate?locationId=$1" >/dev/null 2>&1 || true
  curl -sS -X POST "$API/contacts/search" \
    -H "token-id: $(read_token)" -H 'channel: APP' -H 'version: 2021-04-15' -H 'source: WEB_USER' \
    -H "origin: $ORIGIN" -H 'content-type: application/json' -H 'accept: application/json, text/plain, */*' \
    -d "{\"locationId\":\"$1\",\"pageLimit\":1,\"page\":1}" | jq '{total}'
}

# contacts-scan <loc> [contacts_scan.py args] : paginate ALL contacts via
# /contacts/search/2 and hydrate custom-field VALUES (returned inline). Handy
# examples:
#   contacts-scan <loc> --list-fields
#   contacts-scan <loc> --where 'Membership Name~Gold' \
#       --select 'Contract Start Date,Contract End Date,Membership Status'
#   contacts-scan <loc> --where 'Tags~vip' --csv out.csv
# Injects a fresh token; passes the rest straight to contacts_scan.py.
cmd_contacts_scan() {
  local loc="${1:?usage: contacts-scan <loc> [--where ...] [--select ...] [--out f.json] [--csv f.csv] [--list-fields]}"
  shift || true
  python3 "$DIR/contacts_scan.py" --token "$(read_token)" --api "$API" --loc "$loc" "$@"
}

main() {
  while [[ "${1:-}" == -* ]]; do
    case "$1" in
      -a|--account) ACCOUNT="$2"; shift 2 ;;
      -h|--help) sed -n '2,51p' "${BASH_SOURCE[0]}"; exit 0 ;;
      *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
  done
  local sub="${1:-}"
  shift || true
  case "$sub" in
    unlock)     cmd_unlock ;;
    lock)       cmd_lock ;;
    save)       cmd_save ;;
    vault-add)  cmd_vault_add "$@" ;;
    token-info) cmd_token_info ;;
    refresh)    cmd_refresh ;;
    parse-url)  cmd_parse_url "$@" ;;
    list)       cmd_list "$@" ;;
    folders)    cmd_folders "$@" ;;
    move)       cmd_move "$@" ;;
    enroll-stats) cmd_enroll_stats "$@" ;;
    get)        cmd_get "$@" ;;
    summary)    cmd_summary "$@" ;;
    dump-all)   cmd_dump_all "$@" ;;
    triage)     cmd_triage "$@" ;;
    numbers)    cmd_numbers "$@" ;;
    dialer)     cmd_dialer "$@" ;;
    inbound)    cmd_inbound "$@" ;;
    raw)        cmd_raw "$@" ;;
    post)       cmd_post "$@" ;;
    del)        cmd_del "$@" ;;
    put)        cmd_put "$@" ;;
    nodes)      cmd_nodes "$@" ;;
    fields)     cmd_fields "$@" ;;
    calendars)  cmd_calendars "$@" ;;
    pipelines)  cmd_pipelines "$@" ;;
    dispositions) cmd_dispositions "$@" ;;
    backup)     cmd_backup "$@" ;;
    meta-diff)  cmd_meta_diff "$@" ;;
    forms)      cmd_forms "$@" ;;
    contacts)   cmd_contacts "$@" ;;
    contacts-scan) cmd_contacts_scan "$@" ;;
    ""|help)    sed -n '2,51p' "${BASH_SOURCE[0]}" ;;
    *) echo "unknown subcommand: $sub" >&2; exit 1 ;;
  esac
}

main "$@"
