# GHL Workflow Node Schemas (internal API): reusable across all subaccounts

Every schema below is copied verbatim from real workflow dumps. Use these to build
workflow bodies programmatically instead of clicking in the UI. Placeholders in
`<ANGLE_BRACKETS>` are the only things you swap per build.

---
## 1. Write endpoints & auth

Base `API=https://backend.leadconnectorhq.com`. All calls need header set:
`token-id: <idToken>` (from `./ghl.sh -a <acct> refresh` → accounts/<acct>/token.txt),
`channel: APP`, `source: WEB_USER`, `version: 2021-04-15`, `content-type: application/json`,
`origin: https://client-app-automation-workflows.leadconnectorhq.com`,
**and a real browser `user-agent`** (urllib without one → Cloudflare error 1010; curl's default UA is fine).

| Action | Method + path | Body |
|---|---|---|
| Create draft shell | `POST /workflow/{loc}` | `{"name":"<name>","locationId":"<loc>"}` → returns `{"id"}` |
| Write/replace body | `PUT /workflow/{loc}/{wf}` | Full payload, every omitted top-level field is clobbered. Send all 12 from a fresh GET: `{name, version, parentId, status, workflowData:{templates:[…]}, meta, workflowNote, allowMultiple, removeContactFromLastStep, stopOnResponse, autoMarkAsRead, allowMultipleOpportunity}`. `status:"published"` keeps a live workflow live; a new shell defaults `stopOnResponse:false`, so set it. |
| Add trigger | `POST /workflow/{loc}/trigger` | trigger object with `workflowId` **in the body** plus `status:"draft"`, `triggersChanged:true`, `active:false` (see §5) |
| Update trigger | `PUT /workflow/{loc}/trigger/{tid}` | full trigger object with your edits → `{status:"success"}` |
| Delete trigger | `DELETE /workflow/{loc}/trigger/{tid}` | removes a wrong or duplicate trigger |
| Move to folder | `PUT /workflow/{loc}/move-directory/{wf}` | `{"parentId":"<folderId>"|null}` (or `./ghl.sh -a <acct> move <loc> <wf> <folder>`) |
| Read body | `GET /workflow/{loc}/{wf}?includeScheduledPauseInfo=true` | → `{name,version,parentId,status,workflowData}` (`status:null` = draft) |
| Read triggers | `GET /workflow/{loc}/{wf}?includeTriggers=true` | → `{triggers:[…]}` (no `workflowData`, no `status`) |
| Version history | `GET /workflow/{loc}/{wf}/history` | one row per saved version: `version, updatedAt, updatedBy, status, name, fileUrl` (see §6) |
| Delete | `DELETE /workflow/{loc}/{wf}` | also works on a folder id; removes the workflow's sticky notes too |

`version` on PUT: send the value from the GET (starts at 1). `parentId` = the workflow's
folder id (null = root). Products/custom-fields writes use a DIFFERENT header set: `version:2021-07-28`,
`origin: <your GHL/whitelabel app domain>`.

---
## 2. Node chaining (the `templates` array)

`workflowData.templates` is a flat list. There is NO separate root pointer, the entry
node is the one with **no `parent` and no `parentKey`**.

- **Top-level linear chain:** node0 `{id,order:0,…,next:id1}` (no parent/parentKey) →
  node1 `{id,order:1,parentKey:id0,…,next:id2}` → … last node has `next:""` (Firebase stores it as `null`, which a PUT rejects with 400 "Next is invalid").
  `parentKey` = previous node's id. Top-level nodes have NO `parent`.
- **Inside an if_else branch:** child nodes set `parent` = the branch id AND
  `parentKey` = previous sibling id (or the branch id for the first child).
- Every node: `{"id":<uuid>,"order":<int>,"name":<str>,"type":<str>,"attributes":{…}}`
  plus `next`/`parent`/`parentKey` per above.

---
## 3. Action node schemas (`attributes` shown; wrap in the node envelope from §2)

**email, inline plain-text (NO template file needed):**
```json
{"fieldDefaults":{},"htmlDefaults":{},"attachments":[],"conditions":[],
 "trackingOptions":{"hasTrackingLinks":false,"hasUtmTracking":false,"hasTags":false,"sourceId":"<wf_id>:<uuid>"},
 "html":"<p style=\"margin:0 0 16px 0;font-family:verdana,geneva,sans-serif;font-size:16px;line-height:1.5;\">Hi {{contact.first_name}},</p>…",
 "subject":"<subject>"}
```
**email, builder template (branded):**
```json
{"subject":"<subj>","template_id":"<emailBuilderId>","templatesource":"email-builder",
 "from_email":"{{custom_values.send_from_email}}","from_name":"{{custom_values.send_from_name}}",
 "previewUrl":"<firebase html url>","createdAt":"<iso>","updatedAt":"<iso>","attachments":[]}
```
**sms (template only, no inline):** `{"template_id":"<smsTemplateId>","attachments":[]}`

**wait (duration):**
```json
{"type":"appointment","name":"<name>","cat":"",
 "appointmentStartAfter":{"when":"after","type":"minutes","value":<mins>,
   "distributed":{"months":<m>,"days":<d>,"hours":<h>,"minutes":<min>}},
 "appointmentCondition":"skip","isHybridAction":true,"hybridActionType":"wait",
 "convertToMultipath":false,"transitions":[]}
```
(`value` = total minutes; keep `distributed` consistent. 1 day = 1440.)

**add_contact_tag:** `{"tags":["<tag1>","<tag2>"]}`  (tags auto-created; stored lowercased)
**remove_contact_tag:** `{"tags":["<tag>"],"type":"remove_contact_tag"}`
**add_notes:** `{"type":"add_notes","html":"<note text/merge fields>"}`

**update_contact_field:**
```json
{"type":"update_contact_field","actionType":"update_field_data",
 "fields":[{"field":"<fieldId>","value":"<val>","title":"<Field Name>","type":"date","date":"customDate"}]}
```
(DATE fields: `"type":"date","date":"customDate"`, value can be a merge like `{{datetime_formatter.1.date}}`.
Option/text/number fields: `value` = the literal; the exact `type` string per dataType is worth
confirming in-UI after first build, non-date types tolerate a generic value on PUT.)

**internal_notification (email to staff):**
```json
{"type":"email","email":{"isCloned":false,"html":"<p>…{{contact.name}}…{{contact.phone}}</p>",
 "selectedUser":["<userId1>","<userId2>"],"userType":"user","subject":"<subj>","attachments":[]}}
```
(Get location user ids from any existing internal_notification node on that location.)

**add_to_workflow:** `{"input_trigger_params":false,"type":"add_to_workflow","workflow_id":"<targetWfId>"}`

**create_opportunity:**
```json
{"type":"create_opportunity","fields":[],"pipeline_id":"<pid>","pipeline_stage_id":"<stageId>",
 "opportunity_name":"{{contact.name}} - <label>","opportunity_status":"open","opportunity_source":"","monetary_value":""}
```

### 3b. `workflowsActionType: "INTERNAL"` (node envelope, easy to miss)

Some node types are rejected on PUT with
`"<node name>" action has a corrupted type. Please reload your workflow.` (HTTP 400)
unless the ENVELOPE (not `attributes`) carries `"workflowsActionType": "INTERNAL"`.

Types that need it: `whatsapp_v2`, `internal_update_opportunity`, `internal_create_opportunity`,
`find_opportunity`, `appointment_booking`, `payments_create_invoice`, `payments_create_estimate`,
`proposals_estimates_send_document`, `log-external-call`, `contact_email_verification`,
`edit_conversation`, `live_chat_response`, `internal-delete-contact`, `internal-add-*`,
`grant-*`/`revoke-group-access`, `update_conversation_ai_status`, `workflow_ai_decision_maker`,
`task-notification`. Everything else (email, sms, wait, tags, if_else, create_opportunity,
update_contact_field, internal_notification, add_notes, add/remove_from_workflow) omits it.

**move an opportunity to a stage:**
```json
{"id":"<uuid>","order":0,"name":"Move Stage","type":"internal_update_opportunity",
 "workflowsActionType":"INTERNAL",
 "attributes":{"type":"internal_update_opportunity","allowBackward":true,"__customInputs__":{},
  "__customInputFields__":[
    {"__customInputs__":{},"dataType":"SINGLE_OPTIONS","filterField":"pipelineId","value":"<pid>","valueFieldType":"select"},
    {"__customInputs__":{},"dataType":"SINGLE_OPTIONS","filterField":"pipelineStageId","value":"<stageId>","valueFieldType":"select"}]}}
```

**whatsapp_v2:** `attributes` = `{"type":"whatsapp_v2","template_id":"<meta approved id>",
"from_phone_number":"<waba phone id>","message":"<copy>","toggle_branch":false,
"__customInputs__":{},"cat":"","convertToMultipath":false,"transitions":[]}`.
The node SAVES with `template_id`/`from_phone_number` blank, so you can stage the copy before
the client's WhatsApp is connected. To attach an approved template: `template_id` = template id,
`from_phone_number` = the WhatsApp phone-number **id** from
`GET /phone-system/whatsapp/location/{loc}/phone-numbers` (not the display number), `message` =
template body with `{{1}}`… replaced by merge tags, plus one attribute per variable keyed by the
merge tag itself (`"{{contact.first_name}}":"{{contact.first_name}}"`). Creating the template
itself is covered in `ENDPOINTS.md` → WhatsApp. Note every business-initiated WhatsApp message needs its
own Meta-approved template, so a bilingual sequence is 2 templates per message.

### 3c. Other write shapes proven on a live client build 2026-08-06
- **Pipeline:** `POST /opportunities/pipelines/` `{name,locationId,showInFunnel,showInPieChart,
  useOpportunityProbability,stages:[{name,position,showInFunnel,showInPieChart,stageWinProbability,color}]}` -> 201.
- **Custom field:** `POST services.leadconnectorhq.com/locations/{loc}/customFields`
  `{name,dataType,model,position}` plus **`options`** (NOT `picklistOptions`) for RADIO/SINGLE_OPTIONS.
- **Custom value:** `POST /locations/{loc}/customValues` `{name,value}` only. Sending `locationId`
  in the body is a 422. Empty string value is rejected, send a placeholder.
- **Calendar:** `POST /calendars/` with `calendarType:"round_robin"`,
  `eventType:"RoundRobin_OptimizeForAvailability"`, `slotDuration/slotInterval/slotBuffer` (+`*Unit`),
  `openHours:[{daysOfTheWeek:[0-6],hours:[{openHour,openMinute,closeHour,closeMinute}]}]`,
  `teamMembers:[{userId,priority,selected,locationConfigurations:[...]}]`.
- **Appointment trigger:** `{"type":"appointment","masterType":"highlevel","conditions":[
  {"operator":"==","field":"appointment.eventType","value":"normal",...},
  {"operator":"==","field":"calendar.id","value":"<calId>",...},
  {"operator":"==","field":"appointment.status","value":"confirmed"|"noshow",...}]}`.

---
## 4. if_else node

Envelope `type:"if_else"`. `attributes`:
```json
{"conditionName":"<label>","currentRecipeType":"CUSTOM","if":true,"noneBranchName":"None",
 "operator":"and","version":2,
 "branches":[
   {"id":"<branchId>","name":"<branch name>","operator":"and","showErrors":false,
    "branchNameError":"Branch name cannot be empty!",
    "segments":[{"__segmentId":"<uuid>","operator":"and","conditions":[
      {"conditionType":"contact_detail","conditionSubType":"<FIELD_ID>",
       "conditionOperator":"has_value","__conditionId":"<uuid>","ifElseNodeId":"","isWait":false,
       "nestedDropdownTypes":[…],"allowIsOperatorTypes":[…]}]}]}
 ]}
```
- The if_else node's `next` is an ARRAY of branch ids (one per branch). Child nodes of a branch
  set `parent` = that branch id.
- `conditionSubType` = the custom-field id being tested. `conditionOperator` values seen across
  real dumps: `==`, `!=`, `contain`, `notContain`, `has_value`, `has_no_value`, `>`, `>=`, `<`,
  `<=`, `is`, `is-any-of`, `is-none-of`, `index-of-true`, `index-of-false`. **`less_than` /
  `greater_than` / `is_not` are NOT valid** (they save, then never match). Build from this list.
- `conditionType` values seen live: `contact_detail`, `contact_reply`, `trigger`,
  `inboundWebhookRequest`, `custom_values`, `date_time`, `appointment`, `custom_code`,
  `workflow_contact`, `payment`, `order`, `opportunities`.
- Native **Contact Type** is not a custom field: test it with `conditionSubType:"type"` and
  compare against the stored slug, not the UI label (a label like "Offboarded" can store as
  `archive`).
- Copy the long `nestedDropdownTypes` / `allowIsOperatorTypes` arrays verbatim from any real
  if_else dump on the location (they are static UI hints).

**Branches are ALSO nodes.** `attributes.branches` alone renders nothing. Each branch needs a
stub node in `templates`, and the parent needs the condition-node markers, or the PUT is
rejected with *"If/else branch's parentKey X is not an if/else condition-node"* plus
*"Non-branching node has next as an array"*:
- Parent if_else node envelope MUST carry `"cat":"conditions"` and `"nodeType":"condition-node"`
  (a shell built without them looks fine in the UI but fails every branch PUT).
- Parent `next` = `[branchId1, ..., branchIdN, noneBranchStubId]` (the None stub is an EXTRA id
  beyond `attributes.branches`).
- Yes-branch stub: `{"id":<branchId from attributes.branches>,"parent":<ifElseId>,"order":1,
  "attributes":{"if":false,"conditionName":"Condition","operator":"and","branches":[]},
  "name":<branch name>,"type":"if_else","cat":"conditions","next":<first child id>,
  "sibling":[<every other stub id>],"comments":[],"nodeType":"branch-yes","parentKey":<ifElseId>}`
- None-branch stub: same but `"attributes":{"else":true}`, `"name":"None"`,
  `"nodeType":"branch-no"`. This is where contacts land when no branch matches.
- Child nodes: `parent` = branch id, `parentKey` = branch id for the first child then the
  previous sibling, `next` = next sibling id (a STRING, never an array).

**Branch on which trigger fired.** One workflow with N triggers + one if_else beats N
near-identical workflows:
```json
{"conditionType":"trigger","conditionSubType":"trigger","conditionOperator":"==","conditionValue":"<triggerId>"}
```
POST the triggers first and read their ids back, then PUT the body. Two variants of an offer are
often two PRICES on one product, which a product-level trigger cannot tell apart: filter each
trigger on price instead (`order.line_item_global_price_ids` on `order_submission`,
`payment.global_product_price_ids` on `payment_received`) and branch on trigger id. Pull
`GET /products/{id}/price?locationId=` before designing the routing.

**if_else 10-branch cap.** The UI stops at 10 branches; the API accepts more but the workflow
misbehaves past 10. Chain a second if_else from the None branch instead.

**PUT drops `status`.** The workflow GET does not always echo `status`, so building the PUT
body from the GET silently sends no status and the workflow loses it (it stops reporting
`draft`). Always send `"status": meta.get("status") or "draft"`. Verified on a live build
2026-09-09.

---
## 5. Trigger schemas (`POST /workflow/{loc}/trigger`)

> **The workflow id goes in the BODY as `workflowId` (camelCase), NOT as a `?workflowId=`
> query param.** Posting it as a query param returns `200 {"id":"..."}` so it looks like it
> worked, but the trigger is never bound to the workflow: `?includeTriggers=true` comes back
> `[]` and the id 404s on read. Silent no-op. Verified 2026-08-07.
> The real UI POST body (captured from a HAR) also carries `status:"draft"`,
> `triggersChanged:true`, `location_id` and `company_id`.

Every example below also needs the common envelope:
`{"status":"draft","workflowId":"<wf>","triggersChanged":true,"active":false,"masterType":"highlevel",
"location_id":"<loc>","company_id":"<company>","schedule_config":{}, ...}` (`company_id` is in the
token claims, `./ghl.sh token-info`). Older dumps show `workflow_id` at the top level; send
`workflowId`.

**contact_changed (fires on a field transition):**
```json
{"name":"<name>","type":"contact_changed","active":false,"workflowId":"<wf>","location_id":"<loc>",
 "actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "conditions":[{"operator":"has-changed","field":"contact.<FIELD_ID>","title":"<Field>","type":"text","id":"<FIELD_ID>"}]}
```
**contact_tag (fires when a tag is added):**
```json
{"name":"<name>","type":"contact_tag","active":false,"workflowId":"<wf>","location_id":"<loc>",
 "masterType":"highlevel","actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "conditions":[{"operator":"index-of-true","field":"tagsAdded","value":"<tag>","title":"Tag Added","type":"select","id":"tag-added"}]}
```
**call_status / custom disposition (fires when an SDR dispositions a call):**
```json
{"status":"draft","workflowId":"<wf>","name":"<name>","type":"call_status","masterType":"highlevel",
 "active":false,"triggersChanged":true,"location_id":"<loc>","company_id":"<company>","schedule_config":{},
 "actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "conditions":[{"operator":"==","field":"message.direction","value":"outbound","title":"Call Direction","type":"select"},
               {"operator":"contains-any","field":"custom_disposition","value":["<Disposition Name>"],
                "title":"Custom Disposition","type":"multiselect"}]}
```
The disposition is matched by its **literal display string**, so renaming it in Settings →
Custom Dispositions silently breaks every trigger pointing at the old name. Watch curly
apostrophes (`Can’t Connect / Invalid` is U+2019, not ASCII `'`), copy-paste, never retype.
Native call statuses use `"field":"call_status","value":["busy","voicemail","no-answer",…]` instead
and are unaffected by disposition renames/deletes.

Branching on *which* trigger fired inside the body uses
`{"conditionType":"trigger","conditionSubType":"trigger","conditionOperator":"==","conditionValue":"<triggerId>"}`,
so triggers must be POSTed and read back **before** the body PUT.

**customer_reply (fires on an inbound message, filtered by channel):**
```json
{"type":"customer_reply","conditions":[{"field":"message.type","operator":"==","value":19}]}
```
`message.type` ids, verified from live messages: **19 = WhatsApp, 18 = Instagram DM,
11 = Facebook Messenger, 2 = SMS, 1 = call**. Easy to swap 18 and 19 by mistake, which makes a
"WhatsApp reply" trigger fire on Instagram DMs instead.

**Tag filters on any trigger** (several conditions are ANDed):
`{"operator":"index-of-false","field":"contact.tags","value":"<lowercase tag>","title":"Doesn't have tag","type":"select","id":"doesnot-have-tag"}`
(`index-of-true` / `has-tag` for "Has tag").

**`==` is transition-aware.** A `contact_changed` condition with `==` ("is") fires only when the
field moves INTO that value, not on every save while it already holds it. Writing the same value
back does not re-fire, so you don't need tag gates to stop repeat enrolment from no-op writes.

Other trigger `type`s exist for order/payment/appointment/date, dump an existing workflow that
uses one (`?includeTriggers=true`) to grab its exact shape before building.

---
## 6. Gotchas
- **PUT clobbers EVERY omitted field, not just the obvious ones.** `name`+`version`+`parentId`+`workflowData`
  is enough to create a new draft but is DESTRUCTIVE on an existing workflow. Verified
  2026-08-07: that minimal payload silently reset `status: published -> draft` (workflow stopped running),
  `allowMultiple: true -> false`, `allowMultipleOpportunity: true -> false`, and wiped `workflowNote`.
  `allowMultiple:false` is the nasty one, the contact can then only ever enter ONCE, which quietly breaks
  any workflow a contact is meant to re-enter (call dispositions, ladders, loops).
  **Safe pattern for editing an existing workflow:** GET `?includeScheduledPauseInfo=true`, keep the whole
  object, drop `workflowData`/`fileUrl`/`filePath`/`updatedAt`/`permissionMeta`/`__v`, swap in your new
  `workflowData.templates`, keep the current `version`, and PUT that. Then diff the meta against a
  pre-edit backup to prove nothing else moved.
- Triggers are separate objects, unaffected by the body PUT. To edit one in place,
  `PUT /workflow/{loc}/trigger/{tid}` with the full trigger object.
- **A trigger POST without `status:"draft"` + `triggersChanged:true` is created LIVE.**
  The API accepts `active:false` in the body, returns `200 {"id":...}`, and then stores the
  trigger as `active:true` anyway. Verified 2026-08-07: six freshly built shells all came
  back active until those two keys were added. The workflow itself still being a draft is the
  only thing that stops it firing, which is thin cover if anyone publishes. Always send
  `{"status":"draft","triggersChanged":true,"active":false,...}` and read back with
  `?includeTriggers=true` to confirm. To fix an existing one: `DELETE /workflow/{loc}/trigger/{id}`
  then re-POST with the flags (a plain re-POST duplicates instead of updating).
- **`GET ?includeTriggers=true` does NOT return `workflowData`.** It comes back with the
  triggers array and no `templates`, which reads as "the body PUT failed" when it did not.
  Verify bodies with `?includeScheduledPauseInfo=true` and triggers with `?includeTriggers=true`,
  as two separate calls.
- **There is no trigger-update endpoint via plain POST.** Re-POSTing an existing trigger with `active:false`
  does NOT update it, it creates a DUPLICATE that is still active. The UI manages trigger edits through
  `PUT /workflow/{loc}/{wf}/auto-save` (or `/only-triggers/{wf}`) with the full workflow object plus a
  `newTriggers` array. To simply switch one off or remove it, use the UI, or `DELETE /workflow/{loc}/trigger/{id}`.
- urllib → Cloudflare 1010 unless a browser `user-agent` header is set. curl is fine.
- **Create tags before publishing.** An API-built workflow can reference tag names that do not
  exist on the location, and the builder does NOT flag them red (unlike a missing field or
  calendar). Diff the tag names in your JSON against `GET /locations/{loc}/tags?limit=5000`
  (version `2021-07-28`) and `POST /locations/{loc}/tags {name}` each missing one first.
- **`google_sheets` nodes cache the header row.** Each node stores `sheetHeaders` from when it was
  last saved and writes by `columnRange` letters. Add, remove or reorder sheet columns and every
  existing node silently writes to the wrong column until it is re-saved in the UI. Renaming or
  deleting the tab hard-errors the node. Audit: scan dumps for `attributes.type=="google_sheets"`
  and group by `len(sheetHeaders)`; different widths = nodes saved against different layouts.
- **Who changed this step, and when:** `GET /workflow/{loc}/{wf}/history` returns every saved
  version (`version, updatedAt, updatedBy, status, name, fileUrl`). Each `fileUrl` is a signed
  Firebase URL holding that version's `{templates:[...]}`, fetchable without auth. Diff a node's
  attributes across versions to find the exact save; resolve `updatedBy` via
  `GET services.leadconnectorhq.com/users/?locationId={loc}`. (`/versions`, `/version-history` 404.)
- **Other workflow reads worth knowing:** `GET /workflows/status/search/count-per-step?workflowId=&locationId=`
  (contacts currently waiting on each step), `GET /workflows/sticky-notes-all?workflowId=&locationId=`
  (every canvas sticky note; they are not in the workflow GET).
- Tags are stored lowercased; match that when testing tag conditions.
- Keep everything DRAFT + triggers `active:false` while skeleton-building on a live client location.
- `?includeTriggers=true` and `?includeScheduledPauseInfo=true` return DIFFERENT envelopes.
  Only the latter carries `name`/`status`/`version`/`parentId`/`updatedAt`/`fileUrl`; the former
  returns `{dependentAssets,permissionMeta,triggers,workflowData}`. Asking the trigger envelope for
  `.status` gives `null`, which reads as "draft" and will fool an integrity check. Use both.
- Branch pseudo-nodes are real entries in `templates`: `type:"if_else"`, `order:1`,
  `nodeType:"branch-yes"` (or `"branch-no"` for the None branch), `cat:"conditions"`,
  `sibling:[<other branch ids>]`, `parent`+`parentKey` = the router id. The router itself is
  `order:0`, `nodeType:"condition-node"`, `next:[…branch ids…, noneBranchId]`. The None branch has
  `attributes:{"else":true}` and does NOT appear in the router's `attributes.branches` array.

---
## 7. Documents & Contracts (proposals), proven on a live build 2026-08-11

Same host/header set as workflows. **Two-step create, and the two steps disagree about `type`.**

| Action | Method + path | Body |
|---|---|---|
| List templates | `GET /proposals/templates?locationId={loc}&limit=10` | `limit=50` returns 0 rows, cap it at 10 |
| List (filtered) | `GET /proposals/templates/bulk?type.in[]=proposal&locationId.eq={loc}&skip=0&limit=20` | `skip` is required |
| Read one | `GET /proposals/templates/{id}?locationId={loc}` | full object incl. `pages` |
| Create shell | `POST /proposals/templates` | `{locationId,name,type}`: `type` REQUIRED, only `proposal`/`estimate` (`document`/`contract` = 422 "Invalid document type") |
| Write body | `PUT /proposals/templates/{id}` | full payload and **`type` must NOT be sent** (422 "property type should not exist") |
| Delete | `DELETE /proposals/templates/{id}?locationId={loc}` | soft delete, `deleted:true` |
| Sent documents | `GET /proposals/document?locationId={loc}` | separate collection from templates |

`PUT` requires ALL of: `locationId,name,pages,timezone,grandTotal,variables,recipients,
fillableFields,pricingTables,groups,customValueLinkage,enableAutoSendInvoice,enableDirectPayment`.
The last two must be actual booleans. Omit any and you get a 422 naming it, so the errors are
self-documenting, POST once and read the complaint list.

**Page tree** mirrors the funnel builder: `pages[0].children` = `Image` / `Text` / `TextField` /
`DateField` / `Signature`, each with `component.options` + `responsiveStyles.large`.
Body copy is ONE `Text` element holding the whole document as HTML.

**Tables are a separate `Table` element, not HTML inside `Text`.** The Text editor drops
`<table>` on paste, which is why copy/paste from Word loses tables. Shape:
`{type:"Table",version:1,id:<uuid>,children:[],component:{name:"Table Element",options:{text:"<table><tbody><tr><th colspan=\"1\" rowspan=\"1\" colwidth=\"120\" style=\"border-color: rgb(0, 0, 0); width: 120px\"><p>..</p></th>..</tr><tr><td ..>..</td></tr></tbody></table>"}},responsiveStyles:{large:{...copy from a sibling...}}}`.
A document with tables = a page whose `children` interleave `Text, Table, Text, Table…`; they
render in array order. Content width for `colwidth` sums is 700px. `<ol start="N">` continues
numbering after a table split. Extra `Page` elements in `pages[]` are real page breaks (clone
the existing page shell with a new uuid).

**The trap: `Signature` and `DateField` are absolutely positioned:**
`responsiveStyles.large.position.{top,left}` in px, relative to the parent element they are
nested in. Swap the body text and they no longer sit on the signature block. Cleanest fix: give
each signature block its OWN small `Text` element with the `Signature` nested inside it, so `top`
stays around 40-60px whatever the body length. Still eyeball and drag in the UI; never ship an
API-built document unseen.

**Snapshot debris:** templates imported via snapshot carry `isGhost:true` `TextField`s nested
INSIDE the `Text` element, all bound to `{{location.name}}` (which renders the SUBACCOUNT name,
not the client). They are why old bodies render `{***}`. Drop them when cloning.
