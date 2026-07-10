# GHL Workflow Node Schemas (internal API) — reusable across all subaccounts

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
| Write/replace body | `PUT /workflow/{loc}/{wf}` | `{"name","version","parentId","workflowData":{"templates":[…]}}` — **full payload, clobbers omitted fields** |
| Add trigger | `POST /workflow/{loc}/trigger?workflowId={wf}` | trigger object (see §5); `active:false` = inactive |
| Move to folder | `PUT /workflow/{loc}/move-directory/{wf}` | `{"parentId":"<folderId>"|null}` (or `./ghl.sh -a <acct> move <loc> <wf> <folder>`) |
| Read body | `GET /workflow/{loc}/{wf}?includeScheduledPauseInfo=true` | → `{name,version,parentId,status,workflowData}` (`status:null` = draft) |
| Read triggers | `GET /workflow/{loc}/{wf}?includeTriggers=true` | → `{triggers:[…]}` |

`version` on PUT: send the value from the GET (starts at 1). `parentId` = the workflow's
folder id (null = root). Products/custom-fields writes use a DIFFERENT header set: `version:2021-07-28`,
and the `origin` set to your app domain (`https://app.gohighlevel.com`, or your agency's
white-label domain if you have one).

---
## 2. Node chaining (the `templates` array)

`workflowData.templates` is a flat list. There is NO separate root pointer — the entry
node is the one with **no `parent` and no `parentKey`**.

- **Top-level linear chain:** node0 `{id,order:0,…,next:id1}` (no parent/parentKey) →
  node1 `{id,order:1,parentKey:id0,…,next:id2}` → … last node omits `next`.
  `parentKey` = previous node's id. Top-level nodes have NO `parent`.
- **Inside an if_else branch:** child nodes set `parent` = the branch id AND
  `parentKey` = previous sibling id (or the branch id for the first child).
- Every node: `{"id":<uuid>,"order":<int>,"name":<str>,"type":<str>,"attributes":{…}}`
  plus `next`/`parent`/`parentKey` per above.

---
## 3. Action node schemas (`attributes` shown; wrap in the node envelope from §2)

**email — inline plain-text (NO template file needed):**
```json
{"fieldDefaults":{},"htmlDefaults":{},"attachments":[],"conditions":[],
 "trackingOptions":{"hasTrackingLinks":false,"hasUtmTracking":false,"hasTags":false,"sourceId":"<wf_id>:<uuid>"},
 "html":"<p style=\"margin:0 0 16px 0;font-family:verdana,geneva,sans-serif;font-size:16px;line-height:1.5;\">Hi {{contact.first_name}},</p>…",
 "subject":"<subject>"}
```
**email — builder template (branded):**
```json
{"subject":"<subj>","template_id":"<emailBuilderId>","templatesource":"email-builder",
 "from_email":"{{custom_values.send_from_email}}","from_name":"{{custom_values.send_from_name}}",
 "previewUrl":"<firebase html url>","createdAt":"<iso>","updatedAt":"<iso>","attachments":[]}
```
**sms (template only — no inline):** `{"template_id":"<smsTemplateId>","attachments":[]}`

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
confirming in-UI after first build — non-date types tolerate a generic value on PUT.)

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
- `conditionSubType` = the custom-field id being tested. Common `conditionOperator`:
  `has_value` / `has_no_value` / `is` / `is_not` / `greater_than` / `less_than`.
- Copy the long `nestedDropdownTypes` / `allowIsOperatorTypes` arrays verbatim from any real
  if_else dump on the location (they are static UI hints).

---
## 5. Trigger schemas (`POST /workflow/{loc}/trigger?workflowId={wf}`)

**contact_changed (fires on a field transition):**
```json
{"name":"<name>","type":"contact_changed","active":false,"workflow_id":"<wf>","location_id":"<loc>",
 "actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "conditions":[{"operator":"has-changed","field":"contact.<FIELD_ID>","title":"<Field>","type":"text","id":"<FIELD_ID>"}]}
```
**contact_tag (fires when a tag is added):**
```json
{"name":"<name>","type":"contact_tag","active":false,"workflow_id":"<wf>","location_id":"<loc>",
 "masterType":"highlevel","actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "conditions":[{"operator":"index-of-true","field":"tagsAdded","value":"<tag>","title":"Tag Added","type":"select","id":"tag-added"}]}
```
Other trigger `type`s exist for order/payment/appointment/date — dump an existing workflow that
uses one (`?includeTriggers=true`) to grab its exact shape before building.

---
## 6. Gotchas
- PUT clobbers: always send `name`+`version`+`parentId`+`workflowData`. Triggers are separate objects, unaffected by the body PUT.
- urllib → Cloudflare 1010 unless a browser `user-agent` header is set. curl is fine.
- Tags are stored lowercased; match that when testing tag conditions.
- Keep everything DRAFT + triggers `active:false` while skeleton-building on a live location.
  (Per the safety contract in AGENTS.md, never activate a workflow against real contacts unless
  the user has explicitly asked for it in-session.)
- Build order that works: create the draft shell (`POST /workflow/{loc}`) → `PUT` the full
  `workflowData.templates` body → `POST` each trigger (`active:false`) → verify with
  `./ghl.sh nodes <loc> <wf>` → have a human review in the UI before anything goes live.
