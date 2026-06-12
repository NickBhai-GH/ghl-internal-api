#!/usr/bin/env bash
# GHL internal workflow API toolkit (multi-account).
#
# Layout:
#   accounts/<name>/refresh_token.txt    Long-lived Firebase refresh token (chmod 600).
#   accounts/<name>/token.txt            Short-lived idToken; auto-refreshed when <60s remain.
#   workflows/<location_id>/<wf>.json    Per-workflow dump output.
#   reports/<location_id>-triage.csv     Triage CSV output.
#
# Default account is read from accounts/default (one line, account name) or first dir found.
# Override per-call with `-a <account>`.
#
# Subcommands:
#   token-info                Token claims + expiry.
#   refresh                   Force-mint a new idToken.
#   parse-url <url>           Extract location_id and workflow_id from a GHL URL.
#   list <loc>                List all workflows in a location (id, name, status, updatedAt).
#   get <loc> <wf>            Dump one workflow JSON.
#   summary <loc> <wf>        Pretty-print node list of a previously-dumped workflow.
#   dump-all <loc>            Dump every workflow in a location.
#   triage <loc>              Build CSV: name, status, currently_enrolled, node_count, updated.
#   numbers <loc>             Phone numbers owned by the location (forwarding target, default flag, RingAll users).
#   dialer <loc>              Dialer view: owned numbers + verified caller IDs + default-outbound mapping.
#   inbound <loc>             Raw Twilio inbound config (voice_url, status_callback, etc.).

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCOUNTS_DIR="$DIR/accounts"
OUT_DIR="$DIR/workflows"
REPORT_DIR="$DIR/reports"
API="https://backend.leadconnectorhq.com"
ORIGIN="https://client-app-automation-workflows.leadconnectorhq.com"
FIREBASE_KEY="AIzaSyB_w3vXmsI7WeQtrIOkjR6xTRVN5uOieiE"
REFRESH_THRESHOLD=60

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
  ls "$ACCOUNTS_DIR" 2>/dev/null | head -1
}

acct_dir() {
  local name; name="$(resolve_account)"
  [[ -z "$name" ]] && { echo "ERROR: no account configured. Add accounts/<name>/refresh_token.txt." >&2; exit 1; }
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

read_refresh() {
  local f; f="$(acct_dir)/refresh_token.txt"
  [[ -f "$f" ]] || { echo "ERROR: $f missing." >&2; exit 1; }
  tr -d '\n\r ' < "$f"
}

do_refresh() {
  local refresh resp new_id new_refresh tf rf
  tf="$(acct_dir)/token.txt"
  rf="$(acct_dir)/refresh_token.txt"
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
    printf '%s\n' "$new_refresh" > "$rf"; chmod 600 "$rf"
    echo "refresh_token rotated for $(resolve_account)" >&2
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

main() {
  while [[ "${1:-}" == -* ]]; do
    case "$1" in
      -a|--account) ACCOUNT="$2"; shift 2 ;;
      -h|--help) sed -n '2,22p' "${BASH_SOURCE[0]}"; exit 0 ;;
      *) echo "unknown flag: $1" >&2; exit 1 ;;
    esac
  done
  local sub="${1:-}"
  shift || true
  case "$sub" in
    token-info) cmd_token_info ;;
    refresh)    cmd_refresh ;;
    parse-url)  cmd_parse_url "$@" ;;
    list)       cmd_list "$@" ;;
    folders)    cmd_folders "$@" ;;
    enroll-stats) cmd_enroll_stats "$@" ;;
    get)        cmd_get "$@" ;;
    summary)    cmd_summary "$@" ;;
    dump-all)   cmd_dump_all "$@" ;;
    triage)     cmd_triage "$@" ;;
    numbers)    cmd_numbers "$@" ;;
    dialer)     cmd_dialer "$@" ;;
    inbound)    cmd_inbound "$@" ;;
    ""|help)    sed -n '2,22p' "${BASH_SOURCE[0]}" ;;
    *) echo "unknown subcommand: $sub" >&2; exit 1 ;;
  esac
}

main "$@"
