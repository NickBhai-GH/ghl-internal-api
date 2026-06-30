# GHL internal API — endpoint map

A map of GoHighLevel's **internal** API surface (the one the web UI calls), for composing
calls beyond what `ghl.sh` already wraps. All endpoints are on
`https://backend.leadconnectorhq.com` unless noted, and use the header set described in
[`README.md`](README.md#auth-model) (`token-id`, `channel: APP`, `version: 2021-04-15`,
`source: WEB_USER`, `origin`).

> Undocumented and unsupported. Shapes here were observed from real network traffic and may
> change without notice. Confirm against a fresh capture if a call behaves unexpectedly, and
> read the safety contract in [`AGENTS.md`](AGENTS.md) before any write.

## Status legend

- ✅ **Confirmed** — endpoint shape verified by use; edge cases / gotchas noted inline.
- 🟡 **Captured** — shape known from a HAR or the UI, not yet exercised. Trust but verify.
- 🟢 **Public API too** — also documented at `highlevel.stoplight.io/docs/integrations`, but
  that uses a different auth (OAuth2 / API key), not the internal Firebase token. FYI marker,
  not a recommendation to switch — see [Public API, when to reach for it](#public-api--when-to-reach-for-it).
- 🔴 **Unknown** — capture a HAR before scripting (see [Capturing a new endpoint](#capturing-a-new-endpoint)).

---

## Tier 1 — Foundational (auth, structure, custom data)

### Authentication
- ✅ Firebase refresh-token flow (`POST securetoken.googleapis.com/v1/token?key=<firebaseKey>`)
- ✅ Header set (`token-id`, `channel`, `version`, `source`, `origin`)
- ✅ Auto-refresh when <60s remain on the idToken (see `ghl.sh`)
- ✅ Multi-account via `accounts/<name>/refresh_token.txt`
- 🔴 Public-API OAuth2 flow (`services.leadconnectorhq.com/oauth/token` — `client_id` +
  `client_secret` + `refresh_token`; different scopes from the internal token)
- 🔴 Public-API installable-app (marketplace) flow
- 🔴 Sub-account API key generation (the "Private Integrations" page)

### Locations / Agency
- 🔴 Location list (agency view) / create / update / delete
- 🔴 Location settings (timezone, currency, language), business hours, business profile
- 🟢 Public API: `/locations/`, `/locations/{locationId}` (GET, PUT)

### Custom fields
- ✅ List — `GET /locations/<loc>/customFields`
- ✅ Create — `POST /locations/<loc>/customFields`
  - **Gotcha:** `SINGLE_OPTIONS` needs `options` as a plain string array, **not**
    `picklistOptions`.
- ✅ Delete — `DELETE /locations/<loc>/customFields/<id>` (success body has a typo: `{succeded: true}`)
- 🟡 Update — `PUT` (assumed, not verified)
- 🔴 Field folders, field-level permissions

### Custom values
- ✅ List — `GET /locations/<loc>/customValues`
- ✅ Create — `POST /locations/<loc>/customValues`
- ✅ Delete — `DELETE /locations/<loc>/customValues/<id>`
- 🟡 Update — `PUT` (assumed)

### Tags
- ✅ List — `GET /locations/<loc>/tags`
- ✅ Create — `POST /locations/<loc>/tags` (values are force-lowercased)
- 🔴 Update / rename, delete, folders, bulk tag ops on contacts

### Custom objects
- 🟡 10-per-location cap (hard limit across plans)
- 🔴 Custom object + record CRUD, relationships, permissions

---

## Tier 2 — Revenue-generating (client-facing builds)

### Calendars / appointments
Reads + most writes captured — calendar setup is ~80% scriptable.
- 🟡 List — `GET /calendars/?locationId=<loc>&showThirdParty=false`
- 🟡 Single — `GET /calendars/<id>`
- 🟡 Create — `POST /calendars/` (`personal` type confirmed; other types inferred)
- 🟡 Update — `PUT /calendars/<id>` (full body; likely clobbers like workflow PUT)
- 🟡 Status toggle — `PUT /calendars/<id>/status` body `{isActive}`
- 🟡 Slug validate — `POST /calendars/validate-calendar-slug`
- 🟡 Groups — list `GET /calendars/groups`, create `POST /calendars/groups`,
  slug validate `POST /calendars/groups/validate-slug`, move `PUT /calendars/move-group`
- 🟡 Schedules — update `PUT /calendars/schedules/<id>` (day intervals, timezone);
  list `GET /calendars/schedules/search`
- 🟡 Event notifications — create `POST /calendars/event-notifications` (array; types
  confirmation/reminder/cancellation/reschedule/followup × channel email/sms × receiverType
  contact/assignedUser); list `GET /calendars/event-notifications/list`;
  bulk-update `PUT /calendars/event-notifications/bulk-update`
  - **Gotcha:** unique key `(altId, altType, receiverType, channel, notificationType)` →
    `E11000` dup-key error on collision.
- 🟡 RRULE preview — `POST /calendars/generate-rrule-text`
- 🟡 Connections — `GET /calendars/connections` (zoom/outlook/google/icloud/calendly/ms_teams)
- 🟡 Resources — `GET /calendars/resources/rooms|equipments`
- 🟡 Settings — `GET /calendars/location-settings`, `GET /calendars/user-settings`
- 🟡 Appointment search — `POST /calendars/events/<loc>/search/` (nested filter)
- 🔴 Calendar delete, schedule create, room/equipment create, appointment book/update/cancel,
  block-off times, external-calendar OAuth connect, non-`personal` calendar create bodies
- 🟢 Public API: `/calendars/`, `/calendars/events/`, `/calendars/blocked-slots/`

### Pipelines / opportunities — 🔴 (high value, capture early)
- 🔴 Pipeline + stage CRUD, opportunity CRUD/search, move-stage, monetary value, lost reasons
- 🟢 Public API: `/opportunities/pipelines/`, `/opportunities/search`, `/opportunities/`

### Products / payment links / subscriptions — 🔴
- 🔴 Product CRUD (one-time / recurring / membership), variants, prices, images;
  payment link + order form create; subscription list/cancel; coupons; tax/shipping
- 🟢 Public API: `/products/`, `/products/{id}`

### Invoices / estimates — 🔴
- 🔴 Template CRUD; invoice create/send/void; recurring schedule; estimate create/convert;
  Text-2-Pay; invoice settings
- 🟢 Public API: `/invoices/template/`, `/invoices/schedule/`, `/invoices/`, `/invoices/estimate/`

### Courses / memberships — 🔴
- 🔴 Course CRUD, branding, categories, lessons (video/text/quiz/assignment/PDF), drip,
  offers, member list/progress, quizzes, certificates, domain mapping

---

## Tier 3 — Engagement / outreach

### Workflows
- ✅ List — `GET /workflows/?locationId=<loc>`
- ✅ Get — `GET /workflow/<loc>/<wf>` (nodes may reference a Firebase `fileUrl`)
- ✅ Create shell — `POST /workflow/<loc>` body `{name, locationId}`
- ✅ Update — `PUT /workflow/<loc>/<wf>`
  - **Clobber rule:** PUT nulls any top-level field you omit. Always send the **full payload**
    (`name` + `version` + `parentId` + `workflowData` together). Back up with `get` first.
- ✅ Delete — `DELETE /workflow/<loc>/<wf>`
- ✅ Folders — list / create / move
- ✅ Sticky notes — `POST` / `PATCH`
- ✅ Trigger update — `PUT /workflow/<loc>/trigger/<tid>`
- ✅ Enrollment stats — `GET /workflows/status/search/enroll-stats-cache?workflowIds[]=<wf>&locationId=<loc>`
- 🔴 Trigger create/delete, publish/unpublish toggle, re-enroll all, pause/resume, templates,
  native cross-location copy

### Email templates (builder)
Builder **writes** use `version: 2021-07-28` + a browser `User-Agent` (Cloudflare 1010-bans `python-urllib`), origin `https://email-home-prod.leadconnectorhq.com`. Pass `updatedBy` = the token's `user_id` on writes.
- ✅ List — `GET /emails/builder?locationId=<loc>&limit=<n>` → `{builders, total}`. **Returns root-level only** — add `&parentId=<folderId>` to list a folder's contents (dedup-by-name checks miss in-folder templates otherwise).
- ✅ Get data — `GET /emails/builder/data/<loc>/<tid>?isInternal=false` — MJML `editorData {elements, attrs, templateSettings}`; `attrs[id] = {attributes, content, tagName}` where `content` is the element's inner HTML. Check `errorsPresent`.
- ✅ Create blank — `POST /emails/builder?locationId=<loc>` `{locationId, name, type, subject}` (types: `html|folder|import|builder|blank|ai_template`; name/subject don't stick on create)
- ✅ Create folder — `POST /emails/builder/folder` `{name, locationId, type:"folder", updatedBy}` → `{id}`
- ✅ Clone — `POST /emails/builder/clone` `{locationId, templateId:<src>, name, updatedBy}` → `{id, clone}` (clone a branded master to inherit logo/header/footer)
- ✅ Save data — `POST /emails/builder/data` `{locationId, templateId, updatedBy, dnd, html:"", editorType:"builder", previewText}` (`dnd` = editorData; server compiles the HTML)
- ✅ Update meta — `PUT /emails/builder/meta/<tid>` `{fromName, subjectLine, fromAddress, previewText, locationId, updatedBy, fieldDefaults:{}}` — **the only endpoint that sets subject/sender.** ⚠️ `subjectLine`/`previewText` are **plain text** — use real Unicode, not HTML entities (`&rsquo;` renders literally). Body-content entities are fine.
- ✅ Move to folder — `POST /emails/builder/move` `{id, locationId, parentId:<folderId>, updatedBy}`
- ✅ Delete — `DELETE /emails/builder/<loc>/<templateId>` (note the unusual path order: location before template id)
- 🟡 **Wire into a workflow email step** — set the email node's `attributes` to `{subject, from_email, from_name, template_id, templatesource:"email-builder", previewUrl, createdAt, updatedAt, attachments:[]}` (replaces the inline-`html` shape), then save via the workflow PUT (full payload).
- 🔴 Categories, AI-generated template

> **Recipe — branded template from scratch:** `folder` → `clone` a master → build `dnd` (inject copy into `attrs[id].content`, add an `mj-button` linking via `redirectAction:"url"` + `url`/`href` → `{{custom_values.x}}`) → `data` → `meta` (subject) → `move`.

### Email broadcasts (drip_schedule)
- ✅ List — `GET /emails/schedule?locationId=<loc>...`
- ✅ Meta + stats — `GET /emails/schedule/meta/<loc>/<scheduleId>?campaignStats=true`
- ✅ Per-broadcast metadata — `GET /emails/schedule/<loc>/<scheduleId>?campaignStats=true`
- 🔴 Create / update / cancel / resend / send-test, audience (smart-list) selection
  > ⚠️ Anything that actually **sends** to recipients is off-limits per the safety contract.

### Email statistics
- ✅ Campaign list — `GET /emails/campaigns/`
- ✅ Aggregate — `GET /conversations-reporting/emails/aggregate`
- ✅ Recipient-level — `GET /conversations-reporting/emails`
- ✅ Location rollup — `GET /emails/stats/location/<loc>`
- ✅ Daily breakdown — `GET /emails/stats/daily/<loc>/<campaignId>`
- ✅ Order attribution — `GET /emails/attribution/stats/orders`

### Conversations (SMS / Email / IG / FB / GMB / Voice) — 🔴 (high value)
- 🔴 List/search, single, messages, send (SMS/email/DM/voice), read state, star/archive,
  tags, snippets, auto-replies
- 🟢 Public API: `/conversations/`, `/conversations/messages/`, `/conversations/search/`
  > ⚠️ Sending is off-limits per the safety contract unless the user explicitly asks.

### Forms / Surveys
- ✅ Forms list — `GET /forms/?locationId=<loc>&limit=100`
- 🔴 Form get-single, create, update (fields/redirect/notifications), delete, embed/preview,
  submissions; survey CRUD (may differ from forms)
- 🟢 Public API: `/forms/`, `/forms/submissions/`, `/surveys/`, `/surveys/submissions/`

### Funnels / Sites / Blogs
- ✅ Funnel list — `GET /funnels/funnel/list?locationId=<loc>`
- ✅ Single funnel — `GET /funnels/funnel/<id>?locationId=<loc>` (`._data.steps[]` → pageId map)
- ✅ Domains — `GET /funnels/domain?locationId=<loc>`
- ✅ Page doc — `GET /funnels/page/<pageId>?locationId=<loc>` (→ `pageDataDownloadUrl`, `pageVersion`)
- ✅ **Create step (+page)** — `POST /funnels/funnel/create-step` — header `version: 2021-07-28`
- ✅ **Page autosave** — `POST /funnels/builder/autosave/<pageId>` (full `pageData` inline, `manualSave:true`)
- ✅ **Native drag-and-drop page authoring** — see [`funnel-builder/`](funnel-builder/README.md):
  schema (flat `section.elements` tree), section bg custom values, saved colors, font injection
- 🔴 Step/page delete/reorder/publish, A/B test, SEO meta, pixels; Websites + Blogs CRUD
- ⚠️ Builder writes use **`version: 2021-07-28`** (not 2021-04-15) + a browser `User-Agent`
  (Cloudflare 1010-bans `python-urllib`)

---

## Tier 4 — Operational / infrastructure

### Phone numbers / dialer
- ✅ Numbers list — `GET /phone-system/numbers/v2/location/<loc>?pageSize=100&page=0`
  (wrapped as `ghl.sh numbers`)
- ✅ Dialer config — `GET /phone-system/numbers/location/<loc>/dialer?...showVerifiedCallerIds=true`
  (wrapped as `ghl.sh dialer`)
- ✅ Inbound routing — `GET /phone-system/numbers/inbound?locationId=<loc>&skipNumberPool=true`
  (wrapped as `ghl.sh inbound`)
- 🔴 Number purchase/release, IVR, recording/voicemail config, 10DLC/A2P, RCS/WhatsApp setup

### Domains / DNS — 🔴
- 🔴 Domain list/add/verify (DKIM/SPF/DMARC/CNAME)/delete, subdomain config, SSL

### Email sending infrastructure — 🔴
- 🔴 LC Email / custom SMTP / Mailgun config, dedicated IP, warming, sender auth, bounce webhook

### System emails — 🔴
- 🔴 Welcome / password-reset / booking / membership / invoice email overrides, white-label sender

### Users / teams — 🔴
- 🔴 User CRUD, roles/permissions, calendar + conversation assignment
- 🟢 Public API: `/users/`, `/users/search`

### Webhooks / API keys / Integrations — 🔴
- 🔴 Outbound webhook CRUD, private-integration API keys, marketplace app install
- 🔴 Stripe / PayPal / NMI / Authorize.net / Razorpay, Google/Outlook calendar sync,
  Quickbooks, Shopify, Zoom, Slack, social account connects

---

## Tier 5 — Agency / SaaS / sellable products (all 🔴)

- **Snapshots** — list / create-from-location / apply / load-status / share / versioning.
  High value: needed for client hand-offs.
- **SaaS settings** — plan + pricing config, sub-account limit overrides, credit reselling,
  signup form, white-label branding (logo/colors/app name/favicon/CSS/JS).
- **Marketplace apps**, **Social planner**, **Reputation** (review request/list/respond/widget),
  **AI agents** (config, KB upload, flows, channel deployment), **Media library**,
  **Reporting / dashboards**, **subaccount-level custom CSS/JS**.

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

> HAR files and cURL copies contain **live tokens and account data**. Never commit them — the
> bundled `.gitignore` blocks `*.har`. Delete them when done.

**Use a sandbox.** Before scripting a write against a production sub-account, test it on a
throwaway/sandbox location with zero real contacts. Never let a test fire outbound comms.

## Public API — when to reach for it

The internal API (this toolkit) is the default: already wired up, broader surface, and it
exposes UI-internal features the public API doesn't (sticky notes, MJML builder data, full
workflow CRUD, page autosave). Reach for the public API
(`services.leadconnectorhq.com`, OAuth2) only when:

- an internal endpoint you need has moved or been removed;
- you want a more stable contract that's less likely to break on UI updates;
- you're shipping something for third-party install.

The 🟢 markers above just mean "this also exists publicly" — not a nudge to switch.
