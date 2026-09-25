# GHL Internal Workflow API Toolkit

A small bash toolkit that dumps complete workflow content (every node, SMS body, email HTML, webhook URL, condition, wait timer) from GoHighLevel sub-accounts (works with any GHL whitelabel) as JSON. Built for auditing workflows at scale without taking screenshots.

It uses GoHighLevel's **internal** API (the same one their UI calls), not the public API. The public API only returns workflow name/status/ID. The internal API returns every detail.

> **Using an AI assistant (Claude Code, Cursor, etc.)?** Point it at this repo and have it read
> **[`AGENTS.md`](AGENTS.md)** first: that's the operating manual for an agent driving this
> toolkit on your behalf (bootstrap, safety contract, and recipes for pulling data out / pushing
> config in). [`ENDPOINTS.md`](ENDPOINTS.md) is the wider map of the internal API it can compose against.

## Why this exists

Auditing GHL workflows by clicking each node and screenshotting was slow. One curl call per workflow now dumps the full thing as JSON, ready to feed to any tool, spreadsheet, or LLM.

## Folder layout

```
ghl-internal-api/
├── ghl.sh                              # main script (chmod 700)
├── triage.py                           # enriched triage CSV builder (used by `triage`)
├── export_xlsx.py                      # one-sheet-per-workflow audit xlsx from local dumps
├── accounts/                           # one dir per account/whitelabel, all git-ignored
│   ├── default                         # one line: the default account name
│   └── <name>/
│       ├── refresh_token.txt           # long-lived Firebase refresh token (chmod 600), KEYS TO THE KINGDOM
│       └── token.txt                   # short-lived idToken, auto-rotated (chmod 600)
├── workflows/                          # output directory (git-ignored)
│   └── <location_id>/
│       └── <workflow_id>.json
├── reports/                            # triage/audit output (git-ignored)
├── backups/                            # `ghl.sh backup` snapshots (git-ignored)
├── funnel-builder/                     # native drag-and-drop funnel page authoring
├── ENDPOINTS.md                        # map of the internal API: shapes, status, traps
├── WORKFLOW_NODE_SCHEMAS.md            # node + trigger JSON for building workflows, documents
├── CALENDARS.md                        # calendar build recipe + knob-to-field map
├── AGENTS.md                           # operating manual for an AI assistant driving this repo
└── README.md                           # this file
```

The toolkit is **multi-account**: each `accounts/<name>/` holds the credentials for one
logged-in GHL/whitelabel session. Pick which one a command uses with `-a <name>`; the
default (when `-a` is omitted) is read from `accounts/default`.

## Requirements

- `bash` (any modern version)
- `curl`
- `jq`
- `base64` (GNU coreutils)

All standard on Linux/macOS.

## Setup (one-time)

You need to capture a Firebase **refresh token** from a logged-in GHL browser session. After this, the script keeps itself authenticated forever (until you log out everywhere or change your password).

1. Log in to GHL (or your whitelabel) in Chrome.
2. Open DevTools (F12) → **Network** tab → filter **Fetch/XHR** → clear the log.
3. Reload the page (or click into any workflow).
4. Find a request to `identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken`. If you don't see one, log out and log back in to trigger it. (Easier alternative: right-click anywhere in the Network panel → **Save all as HAR with content** → search the HAR file for `signInWithCustomToken`.)
5. Click that request → **Response** tab → copy the value of the `refreshToken` field (a long string starting with `AMf-...`).
6. Create an account dir and paste the token in as a single line (pick any name you like for the account, e.g. `main`):
   ```
   mkdir -p accounts/main
   echo 'AMf-vBy...' > accounts/main/refresh_token.txt
   chmod 600 accounts/main/refresh_token.txt
   echo 'main' > accounts/default          # make it the default account
   ```
7. Test it:
   ```
   ./ghl.sh refresh
   ```
   You should see token info with `seconds_remaining: 3600`.

Repeat for as many accounts as you manage. Target a non-default one per call with `-a <name>`.
After this, you never need DevTools again.

## Usage

```
./ghl.sh [-a <account>] <subcommand> [args]
```

`<loc>` is a location (sub-account) ID; `<wf>` is a workflow ID. Get both from a GHL URL with `parse-url`.

### Subcommands

| Command | What it does |
|---|---|
| `token-info` | Print current token claims (user, role, expiry, locations). Auto-refreshes if expired. |
| `refresh` | Force a new idToken from the refresh token. Useful if something seems off. |
| `parse-url <url>` | Pull the location and workflow IDs out of a GHL workflow URL. |
| `list <loc>` | List every workflow in a location (id, name, status, updatedAt). |
| `folders <loc>` | List workflow folders (id, name, parentId). |
| `get <loc> <wf>` | Download one workflow's full JSON. Saves to `workflows/<loc>/<wf>.json`. |
| `summary <loc> <wf>` | Pretty-print the node + trigger list of a previously-downloaded workflow. |
| `dump-all <loc>` | Download every workflow in a location. |
| `nodes <loc> <wf>` | Live triggers + node list with content snippets: no local dump needed. |
| `triage <loc>` | Build an enriched CSV: name, status, lifetime + active enrollments, node count, folder, updated. |
| `enroll-stats <loc> <wf>...` | Live enrollment counts for one or more workflows. |
| `fields <loc> [model]` | Custom fields (default `contact` model): name \| dataType. |
| `calendars <loc>` | Calendars: name \| type \| active \| id. |
| `pipelines <loc>` | Opportunity pipelines + ordered stage list. |
| `dispositions <loc>` | Custom Dispositions (the buttons an agent clicks after a call). Lives on `/phone-system/`, not the normal settings API. Workflow triggers match these by **literal name**, so a rename silently kills every trigger pointing at the old string. |
| `forms <loc>` | Forms: name \| id \| field count. |
| `contacts <loc>` | Total contact count (cheap import-status check). |
| `contacts-scan <loc> [...]` | Paginate **all** contacts and hydrate custom-field values inline. Flags: `--where`, `--select`, `--out`, `--csv`, `--list-fields`. |
| `numbers <loc>` | Phone numbers owned by the location (forwarding target, default flag, RingAll users). |
| `dialer <loc>` | Dialer view: owned numbers + verified caller IDs + default-outbound mapping. |
| `inbound <loc>` | Raw Twilio inbound config (voice_url, status_callback, etc.). |
| `raw <path> [version]` | Dump an arbitrary internal-API GET (escape hatch for endpoints this script doesn't wrap). |
| `move <loc> <wf> <folder>` | Move a workflow into a folder (a reversible reorg; `root` = top level). |
| `post <path> <json\|@file> [version]` | **Write.** Authenticated POST to any internal-API path; prints the JSON response. Pass `2021-07-28` as the version for funnels, forms, email builder, products and WhatsApp. |
| `put <path> <json\|@file> [version]` | **Write.** Authenticated PUT. Most internal PUTs replace the whole object, so send the full payload you got from a GET. |
| `del <path> [version]` | **Write.** Authenticated DELETE. |
| `backup <loc> <wf> [label]` | Snapshot meta + real node body + triggers to `backups/`. Run this **before** any edit to a live workflow. |
| `meta-diff <backup_meta.json> <loc> <wf>` | Diff a workflow's settings against a backup. Proves an edit changed only the node tree, and catches the silent clobbers described below. |

### Editing a live workflow without breaking it

A body `PUT` overwrites every field you leave out, not just the node tree. A minimal
`{name, version, parentId, workflowData}` payload will silently reset `status` to draft,
flip `allowMultiple` to false (so a contact can then only ever enter **once**), and wipe
the workflow note. None of that surfaces as an error.

```bash
./ghl.sh backup <loc> <wf> pre_edit          # 1. snapshot first
#                                              2. make your change
./ghl.sh meta-diff backups/pre_edit_*_meta.json <loc> <wf>   # 3. prove nothing else moved
```

Step 3 should print `meta clean: only the node tree changed`. Anything else listed is a
setting you clobbered and need to restore from the backup.

More traps worth knowing:

- **Creating a trigger:** the workflow id goes in the request **body** as `workflowId`, not
  as a `?workflowId=` query param. As a query param the API returns `200 {"id": ...}` but the
  trigger is never bound to the workflow, a completely silent no-op.
- **Send `status:"draft"` and `triggersChanged:true` on every trigger POST.** Without them the
  trigger is stored **live** even when the body says `active:false`.
- **Re-POSTing a trigger duplicates it.** It does not update the old one, so you end up with a
  second, still-active copy. Edit in place with `PUT /workflow/{loc}/trigger/{id}` (full trigger
  object), or `DELETE /workflow/{loc}/trigger/{id}` and create it again.

The named subcommands are read-only except `move` (a folder reorg that touches no contact
data). `post`, `put` and `del` are raw write verbs: they send exactly what you give them, so
treat each one as a deliberate, backed-up, confirmed step per [`AGENTS.md`](AGENTS.md).

See [`ENDPOINTS.md`](ENDPOINTS.md) for the wider map of GHL's internal API surface beyond what
this script wraps, and [`WORKFLOW_NODE_SCHEMAS.md`](WORKFLOW_NODE_SCHEMAS.md) for the node /
trigger JSON needed to **build** workflows via the API (not just read them). Native
drag-and-drop funnel pages: see [`funnel-builder/`](funnel-builder/).

### Typical flow

```bash
# Got a workflow URL from someone?
./ghl.sh parse-url 'https://app.gohighlevel.com/location/Ab12Cd34Ef56Gh78Ij90/workflow/00000000-1111-2222-3333-444444444444'
# → LOCATION_ID=Ab12Cd34Ef56Gh78Ij90
# → WORKFLOW_ID=00000000-1111-2222-3333-444444444444

# Dump it
./ghl.sh get Ab12Cd34Ef56Gh78Ij90 00000000-1111-2222-3333-444444444444
# → saved -> workflows/Ab12Cd34Ef56Gh78Ij90/00000000-...json (11919 bytes)

# Quick look at the nodes
./ghl.sh summary Ab12Cd34Ef56Gh78Ij90 00000000-1111-2222-3333-444444444444

# Everything in a location at once, then triage to CSV
./ghl.sh dump-all Ab12Cd34Ef56Gh78Ij90
./ghl.sh triage   Ab12Cd34Ef56Gh78Ij90

# Or work with the raw JSON directly
jq '.workflowData.templates[] | select(.type=="webhook")' workflows/Ab12Cd34Ef56Gh78Ij90/00000000-...json
```

### Output structure

The dumped JSON has a top-level envelope (name, status, version, etc) plus `workflowData.templates[]`, an array of nodes. Each node looks like:

```json
{
  "id": "uuid",
  "order": 0,
  "type": "slack_message",
  "name": "Send notification to Slack",
  "attributes": {
    "channel": { "id": "...", "name": "finance" },
    "text": "New order from {{contact.name}}",
    "type": "slack_message"
  }
}
```

`attributes` shape varies by node type (sms, email, webhook, condition, wait, branch, etc).

## How it works under the hood

### The endpoint

```
GET https://backend.leadconnectorhq.com/workflow/{LOCATION_ID}/{WORKFLOW_ID}?includeScheduledPauseInfo=true
```

Required headers:
- `token-id: <firebase_jwt>` (this is the auth: note it is NOT `Authorization: Bearer`)
- `channel: APP`
- `origin: https://client-app-automation-workflows.leadconnectorhq.com`
- `accept: application/json, text/plain, */*`

### Auth model

GHL uses Firebase Authentication. The `token-id` header is a Firebase ID token (JWT) issued by `securetoken.google.com/highlevel-backend`, valid for 1 hour. The Firebase project's public Web API key is `AIzaSyB_w3vXmsI7WeQtrIOkjR6xTRVN5uOieiE` (visible in the GHL JS bundle).

To refresh:
```
POST https://securetoken.googleapis.com/v1/token?key=AIzaSyB_w3vXmsI7WeQtrIOkjR6xTRVN5uOieiE
Content-Type: application/x-www-form-urlencoded

grant_type=refresh_token&refresh_token=<your_refresh_token>
```

Response includes a fresh `id_token` valid for another hour, and possibly a rotated `refresh_token`.

### Scope behavior (important)

The minted idToken has a `locations: [<one_id>]` claim, but the backend's workflow endpoint does NOT enforce that array. Authorization is decided from `user_id` + `role` + `type` + the company's location list on the server side. So an agency-admin refresh token grants read access to **every** sub-account that user has admin on, regardless of what the JWT's locations array says.

### Auto-refresh logic

`ghl.sh` checks the idToken's `exp` claim before every API call. If less than 60 seconds remain, it silently runs the Firebase refresh, writes the new id_token to `token.txt`, and proceeds. If Firebase rotates the refresh_token, that's also written back to `refresh_token.txt`.

## Security notes

- `accounts/<name>/refresh_token.txt` is the equivalent of a long-lived password. Anyone with that file can act as you across every sub-account you have admin on. Keep it `chmod 600`. Do NOT commit it to git, paste it in chat, or share it. The bundled `.gitignore` already excludes the whole `accounts/` tree, keep it that way.
- `token.txt` is short-lived (1 hour) but still sensitive while valid.
- `ghl.sh` itself only does GETs: a deliberate safe default. Writes (PUT/POST/DELETE) are
  possible by composing `curl` from the shapes in [`ENDPOINTS.md`](ENDPOINTS.md) using the same
  auth headers; treat them as deliberate, backed-up, confirmed steps (see the safety contract in
  [`AGENTS.md`](AGENTS.md)).
- **Never fire outbound communications** (send SMS/email, trigger broadcasts) against real
  contacts. Read and configure freely; the "send" verb reaches real people.
- This uses GHL's internal API. It's not officially supported and could break or be blocked at any time. Treat it as best-effort tooling, not a contract.

## Troubleshooting

**"Firebase refresh failed" with `INVALID_REFRESH_TOKEN` or `TOKEN_EXPIRED`**
The refresh token has been revoked. Re-capture it (see Setup).

**HTTP 401 / 403 from the workflow endpoint**
Token expired and refresh didn't run, or you don't have access to that location. Try `./ghl.sh refresh` then retry.

**HTTP 404**
Wrong location_id or workflow_id. Use `parse-url` on the actual URL from the GHL UI to make sure they're right.

**Empty `workflowData.templates` array**
The workflow has no nodes (newly created and never edited). Not a bug.

**Script exits silently**
Run with `bash -x ./ghl.sh <args>` to see what's happening. If `base64 -d` complains, your token file may have stray whitespace; `tr -d '\n\r '` should handle it but check.

## License / attribution

MIT, see [LICENSE](LICENSE). Built independently by reverse-engineering the GHL web app's own network traffic.

Not affiliated with or endorsed by GoHighLevel. This uses an undocumented internal API that can change or break without notice, use it on accounts you own or are authorized to administer.
