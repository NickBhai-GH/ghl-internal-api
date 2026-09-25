# GHL internal API: endpoint map

A map of GoHighLevel's **internal** API surface (the one the web UI calls), for composing
calls beyond what `ghl.sh` already wraps. All endpoints are on
`https://backend.leadconnectorhq.com` unless noted, and use the header set described in
[`README.md`](README.md#how-it-works-under-the-hood) (`token-id`, `channel: APP`, `version: 2021-04-15`,
`source: WEB_USER`, `origin`).

> Undocumented and unsupported. Shapes here were observed from real network traffic and may
> change without notice. Confirm against a fresh capture if a call behaves unexpectedly, and
> read the safety contract in [`AGENTS.md`](AGENTS.md) before any write.

## Status legend

- ✅ **Confirmed**: endpoint shape verified by use; edge cases / gotchas noted inline.
- 🟡 **Captured**: shape known from a HAR or the UI, not yet exercised. Trust but verify.
- 🟢 **Public API too**: also documented at `highlevel.stoplight.io/docs/integrations`, but
  that uses a different auth (OAuth2 / API key), not the internal Firebase token. FYI marker,
  not a recommendation to switch, see [Public API, when to reach for it](#public-api-when-to-reach-for-it).
- 🔴 **Unknown**: capture a HAR before scripting (see [Capturing a new endpoint](#capturing-a-new-endpoint)).

---

## Headers and host, the short version

- Host: `https://backend.leadconnectorhq.com` for almost everything. A few shapes were first
  captured on `services.leadconnectorhq.com` (custom fields/values, tags, forms, surveys); the
  same paths answer on the backend host with the internal token.
- `version: 2021-04-15` for workflows, calendars, contacts, documents, reporting.
  **`version: 2021-07-28`** for funnels, forms, surveys, email builder, tags list, bulk contact
  tags, WhatsApp templates, products and custom-field writes. A wrong version usually shows up
  as a 404 or 422, not an auth error.
- **Always send a real browser `user-agent`.** Without one, Cloudflare returns `403 error 1010`
  on many endpoints (`/contacts/*` included), which reads like a permissions problem and is not.
  `ghl.sh` sets one; hand-rolled Python `urllib` does not.
- Auth is the `token-id: <idToken>` header, never `authorization: Bearer`.

---

## Tier 1: Foundational (auth, structure, custom data)

### Authentication
- ✅ Firebase refresh-token flow (`POST securetoken.googleapis.com/v1/token?key=<firebaseKey>`)
- ✅ Header set (`token-id`, `channel`, `version`, `source`, `origin`, browser UA)
- ✅ Auto-refresh when <60s remain on the idToken (see `ghl.sh`)
- ✅ Multi-account via `accounts/<name>/refresh_token.txt`
- 🔴 Public-API OAuth2 flow (`services.leadconnectorhq.com/oauth/token`: `client_id` +
  `client_secret` + `refresh_token`; different scopes from the internal token)
- 🔴 Public-API installable-app (marketplace) flow
- 🔴 Sub-account API key generation (the "Private Integrations" page)

### Locations / Agency
- ✅ Locations visible to an agency token: `GET /locations/search?companyId=<company>&limit=500`
  (`companyId` is in `./ghl.sh token-info`).
  - **Gotcha:** `GET /locations/<id>` returns `403` for BOTH a real location you can't see and a
    garbage id, so a 403 never proves a sub-account exists. Enumerate with `/locations/search`.
- ✅ Audit log: `GET /audit/search?locationId=<loc>&id=<contactId|opportunityId|appointmentId>`
  → field-change history: *who/what/when* changed a contact field, tag, opportunity stage.
  - Do NOT send `limit` (422). Pages are 25 logs; next page needs BOTH `&page=N&cursorToken=<pagination.cursorToken>`
    (cursorToken alone just returns page 1 again). Loop while `pagination.hasMore`.
  - Each log: `type` (UPDATED / TAG_ADDED / MERGE_UPDATED…), `source` (INTEGRATION / WORKFLOW_NEW /
    CONVERSATIONS…), `sourceId` (e.g. the workflow that did it), `changedFields`, full `before`/`after`.
    `changedFields` just says `customFields`; diff `before.customFields` vs `after.customFields` by id
    to see which one moved. `source: INTEGRATION` + `channel: OAUTH` = an installed app wrote it.
  - On an opportunity id it shows CREATED/UPDATED with `pipelineName`/`pipelineStageName` and the
    creating workflow as `sourceId`, the answer to "which workflow made this duplicate opp?".
  - Dead ends: `/contacts/{id}/audits` returns `[]`; `POST /audit/search` 404s. Workflows are
    not in the audit log; use workflow version history (Tier 3).
- ✅ Client portal config: `GET /clientclub/portal-settings/<loc>` → subdomain, custom domain,
  branding (colours, logo, favicon), custom CSS/JS, `totalUsers`, and which portal features are on
  (`locationPermissions.{membershipEnabled, communitiesEnabled, contractsEnabled, …}`).
  Branded-app upgrade check: `GET /reselling/subscription/location/<loc>?productCode=CP_BRANDED_APP_49`
  (`[]` = not subscribed). Membership offers/products are NOT reachable on this token (404 / IAM 401).
- 🔴 Location create / update / delete, settings, business hours, business profile
- 🟢 Public API: `/locations/`, `/locations/{locationId}` (GET, PUT)

### Custom fields
- ✅ List: `GET /locations/<loc>/customFields` (add `?model=opportunity` for opportunity fields)
- ✅ List incl. GHL's **standard** fields -
  `GET /locations/<loc>/customFields/search?documentType=field&model=all&limit=1000&skip=0&includeStandards=true`
  (`includeStandard` without the s is a 422). Without the flag you only get user-created fields.
  - **Gotcha:** a user-created field can sit inside a standard folder ("Contact", "General Info").
    It is still custom. Never label a field standard from its folder; read the `standard` flag.
- ✅ Create: `POST /locations/<loc>/customFields` `{name, dataType, model:"contact", position}`
  (`version: 2021-07-28`). dataTypes: `TEXT, LARGE_TEXT, NUMERICAL, PHONE, MONETORY, CHECKBOX,
  SINGLE_OPTIONS, MULTIPLE_OPTIONS, FLOAT, TIME, DATE, TEXTBOX_LIST, FILE_UPLOAD, SIGNATURE, RADIO`.
  - `SINGLE_OPTIONS`/`RADIO` take `options: ["A","B"]` as a plain string array. `[{key,value}]`
    errors with `v.trim is not a function`; `picklistOptions` errors with "should not exist".
  - Returns 201 `{customField:{id, fieldKey, …}}`; `fieldKey` derives from `name`.
- ✅ Folders: `POST /locations/<loc>/customFields` `{name, documentType:"folder", model:"contact"}`,
  then create fields with `parentId:<folderId>`.
- ✅ Delete: `DELETE /locations/<loc>/customFields/<id>` (success body has a typo: `{succeded: true}`)
- 🟡 Update: `PUT` (assumed, not verified)
- **Gotcha: field type is locked after create.** To change it (e.g. RADIO → CHECKBOX), **delete
  first, then recreate with the identical name**: the `fieldKey` regenerates identical so merge
  tags keep working (create first and GHL suffixes it `_1`). You lose: stored values (scan them
  first with `contacts-scan`), the field's placement on every form/survey (silently stripped), and
  any conditional-logic rule on it. RADIO stores a bare string, CHECKBOX an array, so workflow
  conditions must switch from "is" to "contains".
- **Gotcha: DATE fields truncate the time.** No DATETIME type. A `DATE` field stores midnight
  UTC only, so "wait until <field>" loses the hour. Use a text field or a wait-duration node.
- **Gotcha: LARGE_TEXT holds at least 100,000 characters** via the API (tested 1k → 100k, all
  round-tripped). The often-quoted 5,000 cap is a UI text-area limit, not storage. `maxLength`
  comes back `null`, so 100k is the tested floor, not a proven ceiling.
- **Gotcha: Contact Type is native, not custom.** It never appears in `/customFields`. In
  workflows it is `update_contact_field` with `field:"type"`; in if_else, `conditionSubType:"type"`.
  The UI label and the stored slug can differ, so filter on the slug.
- 🔴 Field-level permissions

### Custom values
- ✅ List: `GET /locations/<loc>/customValues`
- ✅ Create: `POST /locations/<loc>/customValues` `{name, value}` only
  - Sending `locationId` in the body is a 422. An empty-string `value` is rejected; send a placeholder.
- ✅ Folders: same POST with `{name, documentType:"folder"}`, then `PUT` a value with `parentId:<folderId>`
- ✅ Delete: `DELETE /locations/<loc>/customValues/<id>`
- 🟡 Update: `PUT /locations/<loc>/customValues/<id>`

### Tags
- ✅ List: `GET /locations/<loc>/tags?limit=5000` (`version: 2021-07-28`)
- ✅ Create: `POST /locations/<loc>/tags` `{name}` (force-lowercased; returns 201 even if it exists)
- ✅ Bulk add/remove on contacts: `POST /contacts/bulk/tags/update/<add|remove>`
  `{locationId, contacts:[<≤100 contact ids>], tags:[…]}` (`version: 2021-07-28`) →
  `{succeeded, errorCount}`. Batch in 100s with a short sleep.
- 🔴 Rename, delete, tag folders

### Contacts
- ✅ Paginate everything: `POST /contacts/search/2` `{locationId, page:N, pageLimit:100, sort:[], filters:[]}`.
  Returns `customFields[]` **with values inline** (`fieldValueString | fieldValueDate | fieldValue`;
  DATE comes back as epoch ms). Page-based paging works to at least ~8k contacts; the
  `searchAfter` cursor form 400s under the default sort. Wrapped as `./ghl.sh contacts-scan`.
- ✅ Filtered search / server-side counts: `POST /contacts/search`
  `{locationId, page:1, pageLimit:1, filters:[{group:"AND", filters:[{field, operator:"eq", value}]}]}`
  and read `.total`. `group` must be uppercase or it 422s. `not_exists` works for blanks where
  `is_empty` is rejected. Prefer per-value `eq` totals over a client-side tally.
- ✅ Create: `POST /contacts/` (standard contact body)
- ✅ Update custom fields: `PUT /contacts/<id>` `{customFields:[{id, value}, …]}`.
  **Send the contact's FULL existing `customFields` array plus your additions**, not just the
  deltas. Proof loop: `contacts-scan --out before.json` → write → scan again → diff every field
  on every contact.
- 🔴 Delete, merge, bulk import (use the UI for imports)

### Custom objects
- 🟡 10-per-location cap (hard limit, same on every plan). Records inside are unlimited, so
  don't spend a slot on a backend cache nobody looks at.
- 🔴 Custom object + record CRUD, relationships, permissions

---

## Tier 2: Revenue-generating (client-facing builds)

### Calendars / appointments
Create, configure, availability, notifications, grouping and activation are all scriptable.
Step-by-step recipe and knob-to-field map: **[`CALENDARS.md`](CALENDARS.md)**.
- ✅ List: `GET /calendars/?locationId=<loc>&showThirdParty=false` (60+ fields per calendar)
- ✅ Single: `GET /calendars/<id>`
- ✅ Create: `POST /calendars/`, `calendarType` confirmed: `personal`, `round_robin`
  (+ `eventType:"RoundRobin_OptimizeForAvailability"`), `class_booking`. `teamMembers` needs ≥1 entry.
- ✅ Update: `PUT /calendars/<id>` (full doc; strip server-managed keys first, see CALENDARS.md)
  - GHL spells `appoinmentPerSlot` / `appoinmentPerDay` with a typo, and the doc ALSO has the
    correctly spelled pair. Capacity follows the correct spelling; set both.
- ✅ Status toggle: `PUT /calendars/<id>/status` `{isActive}`
- ✅ What can actually be booked: `GET /calendars/<id>/free-slots?startDate=<ms>&endDate=<ms>&timezone=<tz>`
  - **Gotcha:** `openHours` is EMPTY on round-robin calendars with per-member schedules, so
    reading the calendar object says "no availability" when there is. Always check free-slots.
  - **Gotcha:** free-slots returns `{"message":"Calendar is inactive"}` for `event`-type calendars
    with zero `teamMembers` even when `isActive:true`. Quirk, not an outage.
  - Unexplained recurring gap with no GHL event behind it = an external linked calendar the
    internal API can't see.
- ✅ Events in a range: `GET /calendars/events?locationId=&calendarId=&startTime=&endTime=`
- ✅ Slug validate: `POST /calendars/validate-calendar-slug` `{calendarId:"", slug, groupId:""}`
- ✅ Groups: list `GET /calendars/groups?locationId=`, create `POST /calendars/groups`,
  slug validate `POST /calendars/groups/validate-slug`, move `PUT /calendars/move-group`
  `{locationId, providerId:<groupId>, calendarIds:[…]}`
- ✅ Schedules: list `GET /calendars/schedules/search?locationId=&isDefault=true`;
  update `PUT /calendars/schedules/<id>` (only for calendars with a non-null `scheduleId`)
- ✅ Event notifications: list `GET /calendars/event-notifications/list?altType=calendar&altId=<calId>`,
  create `POST /calendars/event-notifications` (array), edit `PUT /calendars/event-notifications/bulk-update`
  - **Gotcha:** unique key `(altId, altType, receiverType, channel, notificationType)` →
    Mongo `E11000` on collision. Creating a calendar already adds the confirmation emails; list first.
- 🟡 RRULE preview: `POST /calendars/generate-rrule-text`
- 🟡 Connections: `GET /calendars/connections?locationId=` (zoom/outlook/google/icloud/calendly/ms_teams)
- 🟡 Resources: `GET /calendars/resources/rooms|equipments?locationId=`
- 🟡 Settings: `GET /calendars/location-settings/<loc>[/<userId>]`, `GET /calendars/user-settings/<loc>/<userId>/features`
- 🟡 Appointment search: `POST /calendars/events/<loc>/search/` (nested AND/OR filter)
- **Public booking link:** `https://api.leadconnectorhq.com/widget/booking/<calendarId>`. The slug
  form is `/widget/bookings/<widgetSlug>` (plural). Singular + slug 404s, and so does the whitelabel
  domain. Group widgets are `/widget/group/<groupId>`.
- **Which page is this calendar on?** Scan funnel page JSON (see Funnels). A calendar element
  serialises as `"calendarId":{"value":"<calendarId>","providerId":"<groupId>"}` and **only `value`
  is authoritative**: `providerId` is the group at the time the element was placed and never
  updates. Group widgets embed as a URL, so also grep `widget/(group|booking)/<id>`.
- **Calendar with a custom form:** the widget runs the form's conditional logic but only acts on
  `disqualifyLead` outcomes; a `redirectToUrl` rule is silently ignored. To send someone elsewhere:
  `{"type":"disqualifyLead","disqualifyAction":"openUrl","disqualifyTiming":"disqualifyAfterSubmit","value":"https://…?email={{contact.email}}"}`
  (merge tags resolve). Hide the form's own submit button; the widget supplies Continue.
- 🔴 Calendar delete, schedule create, room/equipment create, appointment book/update/cancel,
  block-off times, external-calendar OAuth connect, `collective`/`service`/`event` create bodies
- 🟢 Public API: `/calendars/`, `/calendars/events/`, `/calendars/blocked-slots/`

### Pipelines / opportunities
- ✅ List: `GET /opportunities/pipelines?locationId=<loc>` (wrapped as `ghl.sh pipelines`)
- ✅ Create: `POST /opportunities/pipelines/`
  `{name, locationId, showInFunnel, showInPieChart, useOpportunityProbability,
  stages:[{name, position, showInFunnel, showInPieChart, stageWinProbability, color}]}` → 201
- ✅ Opportunity custom fields: `GET /locations/<loc>/customFields?model=opportunity`
- ✅ Lost reasons: `GET /reporting/dashboards/internal-ref/lost-reasons?locationId=`
- ✅ Create / move an opportunity inside a workflow: node shapes in
  [`WORKFLOW_NODE_SCHEMAS.md`](WORKFLOW_NODE_SCHEMAS.md) (`create_opportunity`, `internal_update_opportunity`)
- 🔴 Pipeline update/delete, stage edits, direct opportunity CRUD/search
- 🟢 Public API: `/opportunities/pipelines/`, `/opportunities/search`, `/opportunities/`

### Products / prices / payment links
- ✅ List: `GET /products/?locationId=<loc>&limit=200` → `{products}`
- ✅ Prices of one product: `GET /products/<id>/price?locationId=<loc>` (do this before designing
  any "right thing for the right plan" routing; variants are often prices, not products)
- ✅ Create with prices in one call: `POST /products/`
  ```json
  {"locationId":"<loc>","name":"<name>","productType":"DIGITAL","description":"<p>…</p>",
   "medias":[],"availableInStore":true,"isTaxesEnabled":false,"isLabelEnabled":false,
   "prices":[{"name":"<plan>","type":"one_time","currency":"USD","amount":500},
             {"name":"<plan>","type":"recurring","currency":"USD","amount":100,
              "recurring":{"interval":"month","intervalCount":1},"totalCycles":6}]}
  ```
  The response carries each price's `_id` (needed for payment links and price-level triggers).
- ✅ Payment links: list `GET /payment-links/?altId=<loc>&altType=location&limit=200&offset=0&active=all&search=&sourceType=payments_dashboard`;
  create `POST /payment-links/`
  `{altId, altType:"location", linkName, liveMode, sourceType:"payments_dashboard",
  products:[{_id:<productId>, prices:[{_id:<priceId>, quantityDetails:{fixedQuantity:1}}]}],
  captureCustomerPhone, captureCustomerAddress, allowPromotionCodes, paymentButtonText,
  redirectionDetails:{enabled:false, targetTab:"_self"}, automaticDeactivation:{enable:false, type:"date"},
  branding, termsNote}`
- 🔴 Product update/delete, variants, images, order forms, subscriptions, coupons, tax/shipping
- 🟢 Public API: `/products/`, `/products/{id}`

### Invoices
- ✅ Templates: list `GET /invoices/template?altId=<loc>&altType=location&limit=50&offset=0`;
  create `POST /invoices/template`
  `{altId, altType:"location", name, title, currency, items:[…], businessDetails:{name, website, phoneNo, logoUrl, address:{…}},
  discount:{type:"percentage", value:0}, termsNotes, automaticTaxesEnabled, invoiceNumberPrefix, attachments:[]}`;
  delete `POST /invoices/template/delete` `{altId, altType, id}`.
  If an empty `items` array is rejected, send one zero-amount placeholder line.
- ✅ Invoice layout (labels, visibility, pay-button colour): `GET|POST /invoices/layout?altId=<loc>&altType=location`
  (POST the FULL layout object; back it up first)
- ✅ Invoice settings (business details printed on invoices): `GET|POST /invoices/settings?altId=<loc>&altType=location`
- 🔴 Invoice create/send/void, recurring schedules, estimates, Text-2-Pay
- 🟢 Public API: `/invoices/template/`, `/invoices/schedule/`, `/invoices/`, `/invoices/estimate/`

### Documents & contracts (proposals)
- ✅ Template list / read / create / write / delete, sent-document list: full recipe, page tree,
  table element and signature-positioning trap in
  [`WORKFLOW_NODE_SCHEMAS.md` §7](WORKFLOW_NODE_SCHEMAS.md#7-documents--contracts-proposals-proven-on-a-live-build-2026-08-11).
  Short version: `POST /proposals/templates` needs `type:"proposal"`, then the `PUT` must NOT
  send `type`, and `?limit=50` on the list returns zero rows (cap at 10).

### Courses / memberships 🔴
- 🔴 Course CRUD, lessons, drip, offers, member progress. The portal-level config is readable
  (see Client portal above); offers/products under memberships are not reachable on this token.

---

## Tier 3: Engagement / outreach

### Workflows
- ✅ List: `GET /workflows/?locationId=<loc>`; with folders `GET /workflow/<loc>/list?limit=500&offset=0&sortBy=name&sortOrder=asc`
- ✅ Get body: `GET /workflow/<loc>/<wf>?includeScheduledPauseInfo=true` (nodes may sit behind a Firebase `fileUrl`)
- ✅ Get triggers: `GET /workflow/<loc>/<wf>?includeTriggers=true` (a DIFFERENT envelope: no
  name/status/body. Use both calls.)
- ✅ Create shell: `POST /workflow/<loc>` `{name, locationId}`; folder = same with `type:"directory"`
- ✅ Update: `PUT /workflow/<loc>/<wf>`
  - **Clobber rule:** PUT resets every top-level field you omit: status (a live workflow drops to
    draft), `allowMultiple` (contacts can then only enter once), `stopOnResponse`, `meta`,
    `workflowNote`. Send all 12 fields from a fresh GET: `name, version, parentId, status,
    workflowData, meta, workflowNote, allowMultiple, removeContactFromLastStep, stopOnResponse,
    autoMarkAsRead, allowMultipleOpportunity`. `status:"published"` keeps a live workflow live.
  - The last node's `next` must be `""`; Firebase stores `null`, and PUTting that back is a
    400 "Next is invalid".
  - Around any edit: `./ghl.sh backup` before, `./ghl.sh meta-diff` after.
- ✅ Delete: `DELETE /workflow/<loc>/<wf>` (also works on folders; removes the canvas stickies)
- ✅ Move to folder: `PUT /workflow/<loc>/move-directory/<wf>` `{parentId}` (`ghl.sh move`)
- ✅ Trigger create: `POST /workflow/<loc>/trigger` with `workflowId` **in the body** and
  `status:"draft"`, `triggersChanged:true`, `active:false`. Without those two flags the trigger is
  stored LIVE even though you sent `active:false`. As a `?workflowId=` query param it returns an
  id but binds nothing.
- ✅ Trigger update: `PUT /workflow/<loc>/trigger/<tid>` (full object). A re-POST duplicates.
- ✅ Trigger delete: `DELETE /workflow/<loc>/trigger/<tid>`
- ✅ Version history: `GET /workflow/<loc>/<wf>/history` → every saved version with `updatedBy`
  and a no-auth `fileUrl` to that version's nodes. Answers "who changed this step, and when".
- ✅ Enrollment: lifetime/finished `GET /workflows/status/search/enroll-stats-cache?workflowIds[]=<wf>&locationId=<loc>`;
  currently waiting per step `GET /workflows/status/search/count-per-step?workflowId=&locationId=`
- ✅ Sticky notes: create `POST /workflows/sticky-note?locationId=` `{color, content(HTML), positionX, positionY, width, height, workflowId, locationId}`;
  update `PATCH /workflows/sticky-note?_id=<id>&locationId=`; list all on a canvas
  `GET /workflows/sticky-notes-all?workflowId=&locationId=`. Colours seen: yellow, blue, pink.
  One-per-workflow alternative: the top-level `workflowNote` field (settings panel), set via the full PUT.
- 🟡 Publish a never-published draft by sending `status:"published"` (untested; keeping an
  already-live workflow live this way is proven)
- 🔴 Re-enroll all, pause/resume, workflow templates, native cross-location copy
  - The UI's "copy to another sub-account" copies the shell and triggers but NOT the nodes. Fill
    them with a PUT, and delete the "zombie" custom fields GHL auto-creates for unknown field ids.
- Node and trigger JSON for **building** bodies (email, SMS, waits, tags, if/else branches,
  opportunities, WhatsApp, triggers by type, message-type ids, operator list):
  [`WORKFLOW_NODE_SCHEMAS.md`](WORKFLOW_NODE_SCHEMAS.md).

### Email templates (builder)
Builder **writes** use `version: 2021-07-28` + a browser `User-Agent` (Cloudflare 1010-bans `python-urllib`), origin `https://email-home-prod.leadconnectorhq.com`. Pass `updatedBy` = the token's `user_id` on writes.
- ✅ List: `GET /emails/builder?locationId=<loc>&limit=<n>` → `{builders, total}`. **Returns root-level only**, add `&parentId=<folderId>` to list a folder's contents (dedup-by-name checks miss in-folder templates otherwise).
- ✅ Get data: `GET /emails/builder/data/<loc>/<tid>?isInternal=false`, MJML `editorData {elements, attrs, templateSettings}`; `attrs[id] = {attributes, content, tagName}` where `content` is the element's inner HTML. Check `errorsPresent`.
- ✅ Create blank: `POST /emails/builder?locationId=<loc>` `{locationId, name, type, subject}` (types: `html|folder|import|builder|blank|ai_template`; name/subject don't stick on create)
- ✅ Create folder: `POST /emails/builder/folder` `{name, locationId, type:"folder", updatedBy}` → `{id}`
- ✅ Clone: `POST /emails/builder/clone` `{locationId, templateId:<src>, name, updatedBy}` → `{id, clone}` (clone a branded master to inherit logo/header/footer)
- ✅ Save data: `POST /emails/builder/data` `{locationId, templateId, updatedBy, dnd, html:"", editorType:"builder", previewText}` (`dnd` = editorData; server compiles the HTML)
- ✅ Get meta: `GET /emails/builder/meta/<loc>/<tid>` (incl. `previewUrl`; the GET path has `<loc>`, the PUT path does not)
- ✅ Update meta: `PUT /emails/builder/meta/<tid>` `{fromName, subjectLine, fromAddress, previewText, locationId, updatedBy, fieldDefaults:{}}`, **the only endpoint that sets subject/sender.** ⚠️ `subjectLine`/`previewText` are **plain text**, use real Unicode, not HTML entities (`&rsquo;` renders literally). Body-content entities are fine.
- ✅ Move to folder: `POST /emails/builder/move` `{id, locationId, parentId:<folderId>, updatedBy}`
- ✅ Delete: `DELETE /emails/builder/<loc>/<templateId>` (note the unusual path order: location before template id)
- ✅ **Wire into a workflow email step**: set the email node's `attributes` to `{subject, from_email, from_name, template_id, templatesource:"email-builder", previewUrl, createdAt, updatedAt, attachments:[]}` (replaces the inline-`html` shape), then save via the workflow PUT (full payload).
- 🔴 Categories, AI-generated template

> **Recipe: branded template from scratch:** `folder` → `clone` a master → build `dnd` (inject copy into `attrs[id].content`, add an `mj-button` linking via `redirectAction:"url"` + `url`/`href` → `{{custom_values.x}}`) → `data` → `meta` (subject) → `move`.

### Email broadcasts (drip_schedule)
- ✅ List: `GET /emails/schedule?locationId=<loc>&limit=100&offset=0&emailStatus=all` (limit max ~100; 500 is a 422)
- ✅ Meta + stats: `GET /emails/schedule/meta/<loc>/<scheduleId>?campaignStats=true` (richest single call: sent, delivered, opened, clicked, replied, bounces, rates)
- ✅ Per-broadcast metadata: `GET /emails/schedule/<loc>/<scheduleId>?campaignStats=true`
- 🔴 Create / update / cancel / resend / send-test, audience (smart-list) selection
  > ⚠️ Anything that actually **sends** to recipients is off-limits per the safety contract.

### Email statistics
- ✅ Campaign list: `GET /emails/campaigns/?locationId=<loc>&offset=0&limit=500` (`sourceId` = workflow id)
- ✅ Email actions in a workflow campaign: `GET /emails/campaigns/workflow/actions?locationId=&campaignId=`
- ✅ Aggregate: `GET /conversations-reporting/emails/aggregate?locationId=&sourceId=<workflowId>&source=workflow[&groupBy=createdAt]`
  - For a broadcast use `source=email_marketing_campaign` and `sourceId=<bulkRequestId>` taken off
    the schedule object. The schedule `id` is NOT the `bulkRequestId`.
- ✅ Recipient-level: `GET /conversations-reporting/emails?sourceId=&locationId=&source=&status=<opened|clicked|replied|…>&limit=100&includeTotalCount=true&skip=0`
  (which contacts opened/clicked/replied). `replied` counts email replies only.
- ✅ Location rollup: `GET /emails/stats/location/<loc>`
- ✅ Daily breakdown: `GET /emails/stats/daily/<loc>/<campaignId>`
- ✅ Order attribution: `GET /emails/attribution/stats/orders`

### WhatsApp
- ✅ Templates: list `GET /phone-system/whatsapp/location/<loc>/template`; create `POST` same path
  (`version: 2021-07-28`) →  `{id, status:"PENDING", category}`. Approval took 2 to 18 minutes.
  ```json
  {"cta_url_link_tracking_opted_out":true,"name":"lower_snake_name","language":"en_US",
   "category":"UTILITY","components":[{"type":"BODY","text":"Hi {{1}}, see you at {{2}}.",
   "customVariables":["{{contact.first_name}}","{{appointment.start_time}}"],
   "example":{"body_text":[["Adam","10:00 AM"]]}}]}
  ```
  Meta rejects a body that starts or ends with a variable, and every variable needs an example.
  Put links in as plain text, not variables. Every business-initiated message needs its own
  approved template (a bilingual sequence = 2 templates per message).
- ✅ Phone-number ids for the workflow node: `GET /phone-system/whatsapp/location/<loc>/phone-numbers` (`id` field)
- Attaching a template to a `whatsapp_v2` workflow step: see `WORKFLOW_NODE_SCHEMAS.md` §3b.

### Conversations (SMS / Email / IG / FB / GMB / Voice) 🔴
- 🔴 List/search, single, messages, send, read state, star/archive, snippets, auto-replies
- Inbound channel ids for `customer_reply` triggers are known (WhatsApp 19, Instagram 18,
  Messenger 11, SMS 2, call 1), see `WORKFLOW_NODE_SCHEMAS.md` §5.
- Native Conversation AI only sees the last 10 to 20 messages, not the full thread. If a client
  wants replies drafted from full history, keep a running summary in a LARGE_TEXT field.
- 🟢 Public API: `/conversations/`, `/conversations/messages/`, `/conversations/search/`
  > ⚠️ Sending is off-limits per the safety contract unless the user explicitly asks.

### Forms / Surveys
All on `version: 2021-07-28`.
- ✅ Forms list: `GET /forms/?locationId=<loc>&limit=100`
- ✅ Form get: `GET /forms/<id>` → `{form:{name, formData:{form:{fields:[…]}, …}}}`
- ✅ Form update / rename: `POST /forms/<id>` `{name, formData}` (full `formData`; back it up first)
- ✅ Surveys list: `GET /surveys/?skip=0&limit=N&locationId=<loc>&query=&type=survey`
- ✅ Survey get: `GET /surveys/<id>`
- ✅ Survey update: `POST /surveys/<id>` `{name, formData}`; `formData.slides[]` is the step
  array, each `{id, slideName, button, slideData:[fields]}`. Rating field: `type:"rating"`,
  `iconType:"star"`, `count`, bound to a NUMERICAL custom field.
- 🔴 Form/survey create and delete, submissions list
- **Gotcha: deleting a custom field silently strips it from every form/survey** that used it.
  A delete+recreate needs a follow-up form/survey update to put the new field id back.
- **Gotcha: conditional logic: Show beats Hide.** When a Show and a Hide rule are both true, the
  field is shown. Rules match on `hiddenFieldQueryKey`, not the field id.
- **Gotcha: surveys need a sticky contact.** Turn on the location's sticky-contact setting before
  wiring a multi-step survey that writes custom fields across steps, or submissions orphan.
- **Gotcha: the Custom HTML/Code element eats script.** On save it can drop chunks of pasted JS
  (triggered by `//` comments, regex literals, a quoted lone `/`, non-ASCII characters). Keep any
  inline script dead simple and ASCII-only, then re-pull the form via the API and check it is intact.
- **Gotcha: hosted form and booking widgets use Cloudflare Turnstile**, which fails in headless
  browsers (submit spins forever, `/forms/submit` never fires). Test submits in a real browser.
- 🟢 Public API: `/forms/`, `/forms/submissions/`, `/surveys/`, `/surveys/submissions/`

### Funnels / Sites / Blogs
- ✅ Funnel list: `GET /funnels/funnel/list?locationId=<loc>&limit=&offset=`
- ✅ Single funnel: `GET /funnels/funnel/<id>?locationId=<loc>` (`._data.steps[]` → pageId map)
- ✅ Domains: `GET /funnels/domain?locationId=<loc>` (name is in `.url`; `/domains/` is a 404)
- ✅ Page doc: `GET /funnels/page/<pageId>?locationId=<loc>` (→ `pageDataDownloadUrl`, `pageVersion`).
  The element tree lives at `pageDataDownloadUrl`; this is the durable read.
- ✅ Builder read: `GET /funnels/builder/page/data?pageId=<id>` (the UI's load path; 500s if the
  page lacks `sectionStyles` or the funnel's global sections were never initialised)
- ✅ **Create funnel**: `POST /funnels/funnel/create` `{name, locationId, type:"funnel"}` → `{id}`.
  Then **initialise global sections** or reads 500:
  `POST /funnels/builder/global-sections/<funnelId>?locationId=` `{version:1, sectionData:[]}`.
- ✅ **Delete funnel**: `POST /funnels/funnel/delete` `{funnelId, locationId, userId}` (`userId` = token user)
- ✅ **Rename / settings**: `POST /funnels/funnel/update-settings` with the FULL settings block
  `{locationId, funnelId, funnelPath, funnelName, domainId, faviconUrl, headTrackingCode,
  bodyTrackingCode, allowPaymentModeOption, paymentMode, chatWidgetId, imageOptimization,
  isGdprCompliant, isOptimisePageLoad, stopAllSplitTestsAndReset:null, requireCreditCard,
  storeCurrencyFormatting, autoGenerateSchema}`, each filled from the funnel's `_data` (snake_case there).
- ✅ **Create step (+page)**: `POST /funnels/funnel/create-step`
- ✅ **Page autosave**: `POST /funnels/builder/autosave/<pageId>` (full `pageData` inline, `pageVersion` +1, `manualSave:true`)
  - `section.general.sectionStyles` (the compiled CSS per element id) is MANDATORY or the page
    renders unstyled and the builder read 500s. `funnel-builder/` regenerates it for you.
- ✅ **Native drag-and-drop page authoring**: see [`funnel-builder/`](funnel-builder/README.md)
- **Calendar/form usage scan:** threading the page-doc + Firebase fetches (~16 workers) turns ~350
  sequential calls into well under a minute for a large account.
- **Custom Code element on pages:** it gets NO merge-tag substitution, HTML-escapes content, and
  scripts gated on `window.load` never fire (the page is a Vue SPA). Put live JS in the page's
  Tracking Code (footer) instead and run it via `document.readyState`.
- 🔴 Step delete/reorder, publish, A/B test, pixels; Websites + Blogs CRUD
- ⚠️ Builder writes use **`version: 2021-07-28`** (not 2021-04-15) + a browser `User-Agent`

---

## Tier 4: Operational / infrastructure

### Phone numbers / dialer
- ✅ Numbers list: `GET /phone-system/numbers/v2/location/<loc>?pageSize=100&page=0` (`ghl.sh numbers`)
- ✅ Dialer config: `GET /phone-system/numbers/location/<loc>/dialer?...showVerifiedCallerIds=true` (`ghl.sh dialer`)
- ✅ Inbound routing: `GET /phone-system/numbers/inbound?locationId=<loc>&skipNumberPool=true` (`ghl.sh inbound`)
- ✅ Custom dispositions: `GET /phone-system/call-dispositions` (`ghl.sh dispositions`). Workflow
  `call_status` triggers match these by literal name; a rename silently breaks them.
- **Gotcha: user phone fields lie about IVR forwarding.** `GET /users/?locationId=` can show
  `phone:null` and `defaultIVRChannel:"mobileApp"` for users whose forwarding works fine: the
  IVR rings the mobile app. Verify routing via the number's `inboundCallService` and the IVR
  workflow's connect nodes, not the user record.
- When a team member leaves, check the default number's RingAll list; it can still point at them.
- 🔴 Number purchase/release, IVR config, recording/voicemail settings, 10DLC/A2P

### Reporting / dashboards
- ✅ Dashboard read: `GET /reporting/dashboards/<dashId>?locationId=` (`data.widgets[]` with full options)
- ✅ Widget catalogue: `GET /reporting/dashboards/widgets-definitions?locationId=` (filters and
  date properties per module; opportunities only offer date_added / date_updated / last_status_change_date)
- ✅ Custom metrics: list `GET /reporting/custom-metrics?locationId=&page=1&limit=20`;
  create `POST /reporting/custom-metrics?locationId=` (`locationId` in the body too, else "Location Guard").
  Formula = token list: `{type:"operator",value:"openBrace:operator"}`, metric terms, `divison:operator` (sic), `{type:"number",value:"100"}`.
- ✅ Duplicate: `POST /reporting/dashboards/<id>/duplicate?locationId=` `{locationId, targetLocationId, title, isPrivate}`
- ✅ Edit: `PUT /reporting/dashboards/<id>?locationId=` with header **`x-reporting-api-version: 3`**
  (without it: "outdated dashboard version" whatever you send). Body `{title, activityBuffer:{update:[…], create:[…]}, layout:[…], themeConfig, version:<__v>}`.
  `activityBuffer.add` is silently ignored; `create` is the key. Layout ids are the dashboardWidget `_id`.
  A created widget has no x/y until you send a full layout, and the next PUT 422s until you do.
- ✅ Saved date range: `PUT /reporting/dashboards/<id>/preference`
- **Gotcha:** opportunity widgets count the CURRENT stage only, so stage÷stage conversion ratios can
  exceed 100%. Cohort on `date_added` and use `status` (won/lost) + lost reason instead.

### Users / teams
- ✅ User list: `GET services.leadconnectorhq.com/users/?locationId=<loc>` (resolves `updatedBy` ids)
- 🔴 User CRUD, roles/permissions, calendar + conversation assignment
- 🟢 Public API: `/users/`, `/users/search`

### Domains / DNS 🔴
- 🔴 Domain add/verify/delete, subdomain config, SSL (read of funnel domains is under Funnels)

### Email sending infrastructure / system emails 🔴
- 🔴 LC Email / SMTP / Mailgun config, dedicated IP, sender auth; system email overrides

### Webhooks / API keys / Integrations 🔴
- 🔴 Outbound webhook CRUD, private-integration API keys, marketplace app install
- 🔴 Stripe / PayPal / NMI / Authorize.net / Razorpay, calendar sync, Quickbooks, Shopify, Zoom, social connects

---

## Tier 5: Agency / SaaS / sellable products (all 🔴)

- **Snapshots**: list / create-from-location / apply / load-status / share / versioning.
- **SaaS settings**: plan + pricing config, sub-account limit overrides, credit reselling,
  signup form, white-label branding.
- **Marketplace apps**, **Social planner**, **Reputation**, **AI agents**, **Media library**,
  **subaccount-level custom CSS/JS**.

---

## Admin UI deep links

Handy for hyperlinking assets in audit exports. Base = your app/whitelabel domain.

| Asset | Route |
|---|---|
| Workflow | `/v2/location/<loc>/automation/workflow/<workflowId>` |
| Form | `/v2/location/<loc>/form-builder-v2/<formId>` |
| Survey | `/v2/location/<loc>/survey-builder-v2/<surveyId>` |
| Email template | `/v2/location/<loc>/emails/builder/<templateId>` |
| Custom fields | `/v2/location/<loc>/settings/fields` |
| Funnel page preview | `/v2/preview/<pageId>` |

Spreadsheets allow one clickable link per cell, so give each asset its own column.

---

## Capturing a new endpoint

When you need something marked 🔴:

1. In a logged-in GHL browser tab, open DevTools → **Network**, turn **Preserve log** on,
   filter Fetch/XHR.
2. Perform the action **once** in the UI.
3. Right-click the relevant request → Copy as cURL (or **Save all as HAR with content**).
4. Extract method, URL, query params, the `token-id`-style header set, and the request body.
5. Replicate it with the auth token from `./ghl.sh refresh`. Verify against a sandbox
   sub-account first.

> HAR files and cURL copies contain **live tokens and account data**. Never commit them, the
> bundled `.gitignore` blocks `*.har`. Delete them when done.

**Use a sandbox.** Before scripting a write against a production sub-account, test it on a
throwaway/sandbox location with zero real contacts. Never let a test fire outbound comms.

## Public API: when to reach for it

The internal API (this toolkit) is the default: already wired up, broader surface, and it
exposes UI-internal features the public API doesn't (sticky notes, MJML builder data, full
workflow CRUD, page autosave). Reach for the public API
(`services.leadconnectorhq.com`, OAuth2) only when:

- an internal endpoint you need has moved or been removed;
- you want a more stable contract that's less likely to break on UI updates;
- you're shipping something for third-party install.

The 🟢 markers above just mean "this also exists publicly", not a nudge to switch.
