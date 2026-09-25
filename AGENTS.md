# Operating guide for AI assistants

You are an AI assistant (Claude Code, Cursor, or similar) running in a terminal inside this
repo. A human has pointed you here to help them read data out of, or push configuration into,
**their own** GoHighLevel (GHL) sub-account(s), personal or agency. This file is your manual.
Read it fully before acting.

> GHL's public API only returns workflow name/status/ID. This toolkit talks to GHL's
> **internal** API (the same one the web UI calls), which returns and accepts everything.
> It is undocumented and unsupported: treat every call as best-effort and reversible-by-you.

---

## The safety contract: non-negotiable

Before you do anything, internalize these. They protect the user and the people in their CRM.

1. **Only the user's own accounts.** Operate only on sub-accounts the user owns or is
   explicitly authorized to administer. If that's unclear, ask before the first call.
2. **NEVER fire outbound communications.** Do not send SMS, send email, trigger a broadcast,
   publish/enroll a live workflow against real contacts, or do anything that reaches a real
   recipient. Reading, configuring, and building are fine. The "send" verb is off-limits unless
   the user explicitly, specifically asks for it in this session.
3. **Back up before any write.** Before a `PUT`/`POST`/`DELETE`, dump the current state to a
   local file first (e.g. `./ghl.sh get <loc> <wf>` saves the workflow JSON). Writes are not
   atomic and the internal API has clobber traps (see `ENDPOINTS.md`).
4. **Confirm destructive or bulk operations.** Deletes, mass updates, anything touching >1
   object, describe exactly what you're about to do and get a yes first.
5. **Never commit or print credentials.** `accounts/**` holds live tokens (full account
   access). It is git-ignored. Never `cat` a token into chat, never stage it, never paste it.
6. **Default to read.** The named `ghl.sh` subcommands are GETs, except `move` (a reversible
   folder reorg) and `backup` (writes a local file only). The raw verbs `post`, `put` and `del`
   send whatever body you give them to the live account. Every use of them is a deliberate,
   backed-up, confirmed step, composed from the shapes in `ENDPOINTS.md` /
   `WORKFLOW_NODE_SCHEMAS.md` / `CALENDARS.md`.

---

## Bootstrap (do this once, at the start of a session)

1. **Check tooling:** `bash`, `curl`, `jq`, `base64` must be present. `python3` + `openpyxl`
   only if the user wants `triage`/xlsx export.
2. **Check auth:** run `./ghl.sh token-info`.
   - If it prints token claims with `seconds_remaining > 0`, you're authenticated. Note the
     `role`, `type`, and `location_ids`: they tell you what the user can reach.
   - If it errors with "no account configured" or a missing `refresh_token.txt`, the user has
     not set up credentials yet. Walk them through **Setup** in `README.md` (capturing a
     Firebase refresh token from their logged-in browser). You cannot do this step for them:
     it requires their browser session. Ask them to paste the token into
     `accounts/<name>/refresh_token.txt` themselves.
3. **Confirm the target account.** `./ghl.sh token-info` shows which account/role is active.
   If the user manages several, agree on which `-a <account>` to use before acting.

---

## Recipes: getting data OUT (safe, read-only)

```bash
# Resolve IDs from any GHL workflow URL the user pastes
./ghl.sh parse-url '<url>'

# Inventory a sub-account
./ghl.sh list <loc>                 # all workflows
./ghl.sh folders <loc>              # folder tree

# Pull full workflow content (every node, SMS body, email HTML, webhook, condition, wait)
./ghl.sh get <loc> <wf>             # one
./ghl.sh dump-all <loc>             # everything in the location
./ghl.sh summary <loc> <wf>         # human-readable node + trigger list of a local dump

# Audit-ready exports
./ghl.sh triage <loc>               # enriched CSV (status, enrollments, node count, folder)
python3 export_xlsx.py <loc>        # one-sheet-per-workflow xlsx from local dumps

# Telephony
./ghl.sh numbers <loc>              # owned numbers, forwarding, RingAll users
./ghl.sh dialer  <loc>              # caller IDs + default-outbound mapping
./ghl.sh inbound <loc>              # raw Twilio inbound config

# Then reason over the JSON directly, e.g.
jq '.workflowData.templates[] | select(.type=="webhook")' workflows/<loc>/<wf>.json
```

When the user asks an analysis question ("which workflows email on a failed payment?",
"what's enrolled right now?", "find every webhook URL"), `dump-all` then query the local JSON
with `jq`. Don't re-hit the API per question.

## Recipes: putting config IN (writes: confirmed, backed-up)

Use the raw write verbs, which carry the auth headers and browser user-agent for you:

```bash
./ghl.sh post "/locations/<loc>/tags" '{"name":"my tag"}'
./ghl.sh put  "/workflow/<loc>/trigger/<tid>" @trigger.json
./ghl.sh del  "/workflow/<loc>/trigger/<tid>"
./ghl.sh post "/forms/<id>" @form.json 2021-07-28     # 3rd arg = API version header
```

Take the **endpoint shape + body + gotchas** from `ENDPOINTS.md` (custom fields, values, tags,
contacts, calendars, pipelines, products, invoices, documents, email templates, forms, funnels,
WhatsApp templates, dashboards, workflow CRUD). Workflow bodies and triggers:
`WORKFLOW_NODE_SCHEMAS.md`. Calendars end to end: `CALENDARS.md`. For editing a live workflow
use `./ghl.sh backup` before and `./ghl.sh meta-diff` after (see README).

The standard write loop:
1. **Back up** the current object (`./ghl.sh get ...` or the matching read endpoint).
2. **Show the user** the exact request you'll send and what it changes.
3. **Get confirmation.**
4. Send it. For `PUT`, send the **full payload**: the internal API nulls unset top-level
   fields (the "clobber rule" in `ENDPOINTS.md`).
5. **Read it back** to verify, and confirm no collateral fields were wiped.

---

## When something isn't covered

If the user needs an endpoint not in `ENDPOINTS.md`, the capture loop is: user opens GHL with
DevTools → Network (Preserve log on) → performs the action once → "Save all as HAR with
content" → you read the HAR, extract the request (method, URL, headers, body), and replicate
it. **HAR files contain live tokens and data. Never commit them; `.gitignore` already blocks
`*.har`.** Tell the user that.

## Pointers

- `README.md`: human setup + the full `ghl.sh` command reference.
- `ENDPOINTS.md`: the map of GHL's internal API surface: what's confirmed, exact shapes, and
  the traps. Your knowledge base for composing calls.
- `WORKFLOW_NODE_SCHEMAS.md`: verbatim node/trigger JSON for **building** workflow bodies via
  the API (create-shell → PUT-body → add-triggers). Read before scripting a workflow build.
- `funnel-builder/`: author native drag-and-drop funnel pages via the internal API.
- `CALENDARS.md`: calendar build recipe (create → configure → availability → notifications →
  group → activate → verify free slots) and the knob-to-field map.
- `ghl.sh`: the auth engine, read commands and raw write verbs (`gget()` / `gwrite()` are the
  shared primitives). Read `auth_headers()` to see the exact header set.
