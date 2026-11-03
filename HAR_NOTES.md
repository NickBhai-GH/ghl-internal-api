# GHL internal API: notes from HAR captures

Curated notes on GoHighLevel's **internal** API (the one the web app calls), derived from HAR
captures of the GHL web app: how each service works, the call sequences behind UI actions, and
the gotchas. Companion to [`ENDPOINTS.md`](ENDPOINTS.md) (the endpoint map),
[`WORKFLOW_NODE_SCHEMAS.md`](WORKFLOW_NODE_SCHEMAS.md) and [`CALENDARS.md`](CALENDARS.md).

> Undocumented and unsupported. Every shape here was observed in browser traffic and can change
> without notice. Confirm against a fresh capture before scripting a write, and read the safety
> contract in [`AGENTS.md`](AGENTS.md) first.

- **Your own captures:** run `python3 -I har_index.py` over your HARs. It writes `HAR_ENDPOINTS.md`
  (your private catalogue: every endpoint with query keys, body samples and response shapes) and a
  public-safe `ENDPOINT_INDEX.md`. Search those for an exact path; this file explains how the pieces fit.
- IDs, tokens, emails and names below are placeholders. `app.<your-whitelabel>.com` stands for
  whatever domain your agency logs in on.

Status marks: 🟡 = a 2xx was seen in a capture (the shape is proven in the browser, not yet by a
script); ⚠️ = only errors were seen. ✅ in `ENDPOINTS.md` still means "used in working code".
Nothing here was run live except one read-only GET (membership offers, section 3).

## Read first: corrections to common assumptions

| Topic | Commonly assumed | Captures show |
|---|---|---|
| Trigger create URL | `POST /workflow/{loc}/trigger?workflowId=` | No query string. Body uses camelCase `workflowId`. The UI then does a full-workflow PUT (`only-triggers/{wf}` or `{wf}/auto-save`), which bumps `version` |
| Trigger `active` | send `active:false` | UI sends `active:true` + `status:"draft"`. Scripts using `false` on purpose (inactive drafts) are fine |
| Membership offers/products | not reachable with the internal token | `GET /membership/smart-list/offers-products/{loc}` returns names + ids. Confirmed with one live read-only GET |
| Funnel page publish | separate endpoint, unmapped | Same `POST /funnels/builder/autosave/{pageId}` as Save, with `pageType:"live"` and no `manualSave` |
| Funnel step delete | never captured | `POST /funnels/funnel/delete-step` `{funnelId, stepId}` |
| Form reads | backend `GET /forms/{id}` | Backend host returns metadata only. `services.` host returns `formData` + `versionHistory` |
| `version` header | per-service values | Only two values seen (`2021-04-15`, `2021-07-28`) and they are interchangeable. Calendar UI sends `2021-07-28`, funnels `2021-07-28`. Headers that matter: `x-reporting-api-version: 3` (dashboards), likely `api-version: v2` on phone-system voice-call |
| Bar-chart `groupBy` type | `type:"text"` | UI sends `type:"field"`. `text` also worked live, so both are accepted |
| Custom-metric evaluate | body has `locationId` | UI also sends `chartType`; `locationId` goes in the query string |
| Opening a dashboard | read-only | UI PUTs `preference` and `widget-preference` on load |
| HAR auth headers | n/a | Chrome exports are sanitized (no Authorization/Cookie headers). A "no auth" row may just be a stripped header. Response bodies (refreshToken etc.) are still there |

## Contents

1. Headers, auth and login, agency and platform services
2. Workflows, CRM data, calendars, phone
3. Funnels, forms, surveys, emails, brand boards, membership
4. Reporting and dashboards
5. Test sub-account sweep: write recipes, pages that write on open, gaps

---

# 1. Headers, auth, platform services

Status: 🟡 304 = only cached 304s were seen.

**Big caveat first: Chrome's default HAR export is "sanitized".** Not one request in such a HAR has an `Authorization` or `Cookie` header, and no response has `Set-Cookie`. Response bodies are kept. So when a row below says "no auth header", a stripped `Authorization` header may be hiding there.

## Headers by service

Origin families (what the web app sends, one per micro-frontend):
- **APP** = the whitelabel shell `https://app.<your-whitelabel>.com` (or `app.gohighlevel.com`)
- **WF** = `https://client-app-automation-workflows.leadconnectorhq.com`
- **CAL** = `https://calendar-app.leadconnectorhq.com`
- **PB** = `https://page-builder.leadconnectorhq.com`
- **EB** = `https://email-builder-prod.leadconnectorhq.com` / `https://email-home-prod.leadconnectorhq.com`
- **FSB** = `https://leadgen-apps-form-survey-builder.leadconnectorhq.com`
- **PUB** = public pages (`lclink.co`, `link.apisystem.tech`)

`referer` is always the origin plus `/` (2134 of 2398), or a full page URL on public pages. Every authenticated GHL call sends `channel: APP` and `source: WEB_USER`; no other values appear (the only exception is the public chat widget, `source: custom-code`).

| Host | First path segment | `version` sent (count) | Origin | Extra headers seen |
|---|---|---|---|---|
| backend | `oauth` | 2021-07-28 (73), 2021-04-15 (2, whitelabel call from WF) | APP | `x-dr-res-id: email::<email>` (login/email only), `refresh-token` (login/token), `device-id` (login/current). `token-id` is sent as an empty string on login/email |
| backend | `users` | 2021-07-28 (44), 2021-04-15 (1) | APP, CAL | none |
| backend | `companies` | 2021-07-28 | APP | none |
| backend | `locations` | 2021-07-28 (98), 2021-04-15 (27) | APP, CAL, EB | `internal-channel: email-builder` + `location-id: <loc>` (email builder only) |
| backend | `custom-menus`, `notifications`, `onboarding`, `launchpad`, `internal-tools`, `reselling`, `affiliate-*`, `ad-publishing`, `feature-permissions` | 2021-07-28 | APP | none |
| backend | `saas-billing-v2` | 2021-07-28 (52), 2021-04-15 (8) | APP, PB, WF | none |
| backend | `saas_service` | 2021-04-15 or none | WF | none |
| backend | `integrations` | 2021-07-28 (12, APP), 2021-04-15 (5, WF) | APP, WF | none |
| backend | `marketplace` | 2021-04-15 | WF | `developer_version: ubp` (billing/usage only) |
| backend | `appengine` | 2021-04-15 (8), 2021-07-28 (2) | APP | none |
| backend | `ai-employees` | 2021-07-28 | WF | none |
| backend | `workflow` | **none** (21), 2021-04-15 (5); `source` missing on 9 | WF | none |
| backend | `workflows`, `workflows-marketplace`, `associations`, `contacts` | 2021-04-15 | WF | none |
| backend | `calendars` | **2021-07-28 (176)**, 2021-04-15 (3) | CAL, APP | none |
| backend | `funnels` | 2021-07-28 (191) | PB, APP | `developer_version: ""` (empty) on funnel/fetch, page/list, page/{id}, lookup/list, builder/{id}, domain |
| backend | `emails`, `brand-boards`, `snippets`, `email-ai`, `countdown-timer`, `funnel-ai` | 2021-07-28 | EB, PB | none |
| backend | `custom-data`, `custom-fields`, `links`, `businesses` | 2021-07-28 mostly | EB | `internal-channel: email-builder`, `location-id: <loc>` |
| backend | `forms` | 2021-04-15 (8), 2021-07-28 (7) | WF, PB, APP, PUB | public `forms/form-survey-event`: `timezone`, `fullurl`, `x-parent-trace-context`, no token |
| backend | `reporting` | 2021-07-28 (259, shell widgets), **2021-04-15 (157, dashboards)** | APP | `x-reporting-api-version: 3` on every `/reporting/dashboards*`, `custom-metrics*`, `ads-manager/*`, `opportunities/sales-velocity` call |
| backend | `phone-system` | 2021-04-15 (62), 2021-07-28 (29) | APP | `api-version: v2` on `/phone-system/voice-call/location/...` only |
| backend | `opportunities`, `cpaas` | 2021-04-15 | APP | none |
| backend | `objects` | 2021-07-28 (19, APP), 2021-04-15 (8, WF) | APP, WF | none |
| backend | `membership` | 2021-04-15 (17), 2021-07-28 (6) | APP | `contenttype: application/json` (sic) on `smart-list/offers-products`; 17 of 23 carry no token-id |
| backend | `conversations` | 2021-07-28 (11), 2021-04-15 (4) | APP | none |
| backend | `payments`, `products` | 2021-07-28 | APP, CAL | `developer_version: ""` |
| backend | `stats`, `attribution_service` | none | APP, PUB | public tracking, no token, `timezone` |
| services | `agency-dashboard-api` | 2021-04-15 | APP | none |
| services | `agent-studio`, `ai-wrapper`, `labs`, `marketplace` | 2021-07-28 | APP | none |
| services | `copilot` | 2021-07-28 | APP | `developer_version: ""` on most |
| services | `forms`, `surveys`, `objects`, `opportunities`, `payments`, `products`, `brand-boards` | 2021-07-28 | FSB, APP | none |
| services | `locations` | 2021-04-15 (195), 2021-07-28 (31) | APP, FSB | the 195 shell GETs of `/locations/{id}/customFields` and `/customValues` carry **no token-id** (see gotcha 4) |
| services | `saas_service` | 2021-04-15 | APP | none |
| services | `oauth` (changePassword) | 2021-07-28 | APP | no token (reset-link flow) |
| services | `chat-widget/public/config` | none, no channel | APP | `widget-id: <id>`, no token |
| services | `funnels/funnel/geo-location`, `workflow` | none | APP, WF | public |
| services.msgsndr.com | `attribution_service` | none | APP | public, no token |
| widgets.leadconnectorhq.com | `chat-widget` | none | APP | public, no token |

Shell telemetry headers (`app-name: spm-ts`, `route-name`, `route-path`, `route-pattern`, `x-translations-lang: en-US`) ride on 929 shell calls. `ghl.sh` never sends them and its calls work, so treat them as optional. `route-path` contains real location ids and sometimes the login email: never copy it.

Conclusions:
1. **`version` does not gate anything we can see.** Only two values exist. 13 paths were sent with both values and succeeded with both; no path fails on one value and works on the other. Each micro-frontend picks its own: WF family and agency-dashboard-api send 2021-04-15, almost everything else sends 2021-07-28.
2. **`origin` follows the micro-frontend**, not the endpoint. No HAR shows an origin-based rejection. `ghl.sh` sends the WF origin for everything.
3. **Headers that are really needed beyond the base set:** `x-reporting-api-version: 3` for dashboards. Probably `api-version: v2` for `/phone-system/voice-call/location/*` (always sent, untested without). The email-builder `internal-channel` / `location-id` pair and the empty `developer_version` look optional (the same paths succeed without them from other apps).
4. `token-id` is the Firebase idToken in 1933 of 1963 calls. The other 30 are the empty string on login calls.

Common misreadings:
- Calendar APIs are often documented with `version: 2021-04-15`. The calendar app actually sends **2021-07-28** (176 of 179). Harmless (both work).
- Reports differ on whether bare curl passes Cloudflare (one view: 1010 and services 403s without UA + sec-ch-ua + Referer + Origin; another: curl's default UA passes and only `Python-urllib` is banned). Browser captures cannot settle this. Sending a real browser `user-agent`, as `ghl.sh` does, avoids the question.

## Auth and login

Two token systems run side by side:
- **Firebase** (what the toolkit uses): idToken (1h, sent as `token-id`) plus refresh token (`AMf-...`, ~480 to 520 chars), project `highlevel-backend`, public web key `AIzaSyB_w3vXmsI7WeQtrIOkjR6xTRVN5uOieiE` (same key in every HAR and every whitelabel).
- **GHL native**: `authToken` (JWT, 1h), `refreshToken` (JWT, 30 days), plus legacy v1 `jwt` / `refreshJwt` (1h / 30 days). Used by `/oauth/2/login/token`. Not needed by the toolkit.

### Login sequence

| # | Call | Body / result |
|---|---|---|
| 0 | `GET backend/companies/branding?domain=app.<whitelabel>` (token-id empty) | `{exists, info:{brandId, companyId, logoURL, ssoSettings:{enabled,...}, whitelabelLoginConfig:{isGoogleLoginEnabled}}}`. Gives the `companyId` the login body needs. Only seen when recording starts before the login page loads. |
| 1 | `POST backend/oauth/2/login/email` | `{domain:"app.<whitelabel>", subdomain:"app", email, password, deviceId:<uuid>, deviceType:"web", deviceName:<UA>, companyId}` -> 201 `{email, phone, totpEnabled}`. Bad password: 400 `Invalid email or password`. |
| 2 | same call + `otpChannel:"phone"` or `"email"` | -> 201 `{token:<36-char OTP session id>}`, code is sent |
| 3 | same call + `otpChannel, otp, token:<from step 2>, backupCode:false` | -> 201 `{token:<Firebase custom token>, apiKey, userId, companyId, role, type, name, permissions:{workflowsEnabled, workflowsReadOnly}, authToken, refreshToken, jwt, refreshJwt}` |
| 4 | `POST identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken?key=<web key>` | `{token, returnSecureToken:true}` -> `{idToken, refreshToken:"AMf-...", expiresIn:"3600", isNewUser}` |
| 5 | `POST identitytoolkit.googleapis.com/v1/accounts:lookup?key=<web key>` | `{idToken}` -> `{users:[{localId, validSince, lastLoginAt, createdAt, customAuth, lastRefreshAt}]}` |
| 6 | App boot | `GET /users/<userId>`, `/onboarding/version/<companyId>`, `/saas-billing-v2/billing-config/COMPANY/<companyId>`, `services/labs/feature-flags/company/<companyId>`, `/companies/<companyId>`, `/custom-menus/`, `/notifications/users/<userId>`, `/internal-tools/billing/*` |
| 7 | Agency dashboard | `GET /locations/search?companyId&deleted=false&limit[&query]`, `POST /locations/ids {ids:[...]}` (locations domain, documented elsewhere) |
| 8 | **Sub-account switch** | `POST backend/oauth/2/login/signin/refresh?version=2&location_id=<loc1>,<loc2>,...` body `{}`, header `token-id: <current idToken>` -> `{token:<new custom token>}`, then steps 4 and 5 again |

Some captures show 4 login/email calls (an OTP resend, by the look of it). TOTP (`totpEnabled:true`) was never captured.

What the tokens carry (claim names only):
- Custom token from step 3 or 8: issuer `default-crm-marketplace@highlevel-backend.iam.gserviceaccount.com`, 1h, claims `{user_id, company_id, role, type, version, locations, permissions, primaryUser}`.
- Firebase idToken: same GHL claims plus Firebase ones, issuer `https://securetoken.google.com/highlevel-backend`, 1h.
- Agency users (`type:"agency"`) get `locations: []` at login. Step 8 puts the `location_id` list into the claim. The app sends every sub-account opened this session, so the list grows (seen 1, 2, 6, 8, 27, 64 and 72 ids). Agency-level pages send `location_id=` empty.
- Account users (`type:"account"`) get their locations in the login token already, and may never call signin/refresh.
- The locations claim is not enforced for agency tokens: 21 location-scoped calls for ids outside the claim succeeded. This matches the README.

Other auth endpoints:
- `GET backend/oauth/2/login/current` (headers token-id + `device-id`) on page reload returns the same bundle as step 3, custom token included.
- `POST backend/oauth/2/login/token` (header `refresh-token: <v1 refreshJwt>`, body `{refreshTokenV2:<v2 refreshToken>}`) returns `{v1JWTs:{jwt, refreshJwt}, jwt, authToken, refreshToken}`, both refresh tokens rotated. This is the GHL-native refresh. It does not return a Firebase custom token.
- `POST securetoken.googleapis.com/v1/token?key=<web key>` form `grant_type=refresh_token&refresh_token=...` (sent by the page-builder iframe). Matches `ghl.sh do_refresh`.

### Re-capturing a refresh token

Confirmed: the `signInWithCustomToken` response has `refreshToken` (`AMf-...`). Chrome's default sanitized HAR export keeps response bodies, so a normal export works. Preserve log matters, because login navigates (`/?logout=true` to the dashboard).

Corrections and additions:
1. **No need to log out and back in** (that costs an OTP). Every sub-account switch fires `signin/refresh` and then `signInWithCustomToken` with a fresh refresh token. Many captures have this with no login at all. Recipe: Preserve log on, open or switch to any sub-account, save the HAR, take the **last** `signInWithCustomToken` response's `refreshToken`.
2. A plain reload does not always fire it: one capture had only `login/current`. That response holds a custom token valid for 1h. Fallback (live call): POST it to `signInWithCustomToken` to mint a refresh token.
3. **Dead refresh tokens show up in `validSince`.** `accounts:lookup` returns `validSince` (the time Firebase revokes tokens back to). Logging in does NOT move it: one agency's value stayed put across months of logins, while another's moved forward when its tokens were revoked, which forced a re-capture. If `ghl.sh refresh` fails with INVALID_REFRESH_TOKEN / TOKEN_EXPIRED, re-capture.

## oauth

GHL's own user-session service plus whitelabel and marketplace-page config. **None of the 8 is a marketplace app install or a public-API OAuth flow.** The agency-to-location token exchange is `signin/refresh`.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `backend/oauth/2/login/email` | 3-step password + OTP login (above) | 🟡 |
| POST | `backend/oauth/2/login/signin/refresh?version=2&location_id=<csv>` | location switch: new Firebase custom token scoped to the listed sub-accounts | 🟡 |
| GET | `backend/oauth/2/login/current` | re-issue the full login bundle for the current session (page reload) | 🟡 |
| POST | `backend/oauth/2/login/token` | GHL-native refresh (v1 + v2 refresh JWTs) | 🟡 |
| GET | `backend/oauth/whitelabel/<companyId>` | agency marketplace settings: `{config:{enableThirdParty, enableLeadConnector, hideLabel, clientBlackList:[appId], allowMarketplace, allowNewPublicApps, autoApproveLeadConnectorApps}}` | 🟡 |
| GET | `backend/oauth/sidenav-custom-pages?companyId[&locationId]` | marketplace-app pages pinned in the sidebar (always `[]` in the captures) | 🟡 |
| GET | `backend/oauth/sso/<appId>/session-details` | SSO payload for a marketplace custom page: `{data:"U2FsdGVkX1..."}` (CryptoJS AES ciphertext the app decrypts with its SSO key) | 🟡 |
| POST | `services/oauth/users/changePassword` | set password from a reset link: `{userId, newPassword, token:<40-char reset token>}` -> `{success, message:"Password Set Successfully"}`, no token-id | 🟡 |

Gotchas:
- login/email sends `token-id: ""` and `x-dr-res-id: email::<email>`. Don't script logins; OTP makes it interactive anyway.
- `signin/refresh` returns a custom token, not an idToken. It must go through `signInWithCustomToken`.

## users

User profile and the user list with roles and permissions: what an audit of who can do what needs.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/users/<userId>` | one user: `{id, name, firstName, lastName, email, phone, permissions:{41 flags}, roles:{type, role, locationIds}, scopes, scopesAssignedToOnly, isAgencyOwner, restrictSubAccount, pinnedLocations, recentVisited, platformLanguage, totpEnabled, isPasswordPending, loginCount, ...}` | 🟡 |
| GET | `backend/users/search?companyId=<companyId>&locationId=<loc>&limit=500&skip=0` | users with access to a sub-account: `{users:[{id, name, email, phone, roles:{type, role, locationIds, restrictSubAccount}, permissions, scopes, permissionTemplateId, lastLoginTime, dateAdded}], count}` | 🟡 |
| GET | `backend/users?locationId=<loc>` | returned `{users:[]}` in the one capture. Use `/users/search` | 🟡 |

Body / response notes:
```json
{"roles": {"type": "account", "role": "user", "locationIds": ["<loc>"], "restrictSubAccount": false},
 "permissions": {"workflowsEnabled": true, "workflowsReadOnly": false, "contactsEnabled": true, "assignedDataOnly": false, "...": "..."},
 "lastLoginTime": "<iso>", "permissionTemplateId": "<id>"}
```
`roles.type`/`role` pairs seen: account/admin (95), account/user (23), agency/admin (5). Permission flags include `assignedDataOnly`, `workflowsReadOnly`, `customMenuLinkWrite`, `exportPaymentsEnabled`, `refundsEnabled`, `settingsEnabled`.

Gotchas: agency users appear in `/users/search` for a location too; filter on `roles.type`. No user writes were captured.

## companies

The agency record, its brands and its whitelabel settings.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/companies/<companyId>` | agency: name, domain, subdomain, plan, currency, timezone, `isReselling`, `customJavascript`, `customCss`, theme, ToS/privacy acceptance, onboardingInfo | 🟡 |
| GET | `backend/companies/branding?domain=app.<whitelabel>` | pre-login lookup, domain -> `companyId`, brand, SSO settings | 🟡 |
| GET | `backend/companies/brand/<brandId>?companyId&locationId` | one brand: domain, logo, `customCss`, `customJavascript`, `isDefault`, `whitelabelLoginConfig` | 🟡 |
| GET | `backend/companies/brand/<companyId>/all-brands` | all brands of the agency | 🟡 304 |

Gotchas: `companies/<id>` exposes the agency's whitelabel custom JS/CSS, useful when a sub-account behaves oddly (third-party customizer scripts, see Noise). Company-scope calls 401 for `type:"account"` tokens.

## agency-dashboard-api

Agency dashboard money tiles (Stripe-connected revenue, MRR, rebilling). Useful for an agency-level audit. Host is `services`, version 2021-04-15. `<stripeAccount>` is the agency's Stripe Connect account id.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/agency-dashboard-api/customer/<stripeAccount>/total?companyId` | customer count `{data:{count}}` | 🟡 |
| GET | `/agency-dashboard-api/customer/<stripeAccount>/monthly?companyId&from&to&timezone` | customers per month | 🟡 |
| GET | `/agency-dashboard-api/account-revenue/<stripeAccount>/monthly-revenue?companyId&from&to&type=Monthly&timezone` | revenue per month (`value, metricValueUsd, metricCount, uniqueLocationCount`) | 🟡 |
| GET | `/agency-dashboard-api/account-revenue/<stripeAccount>/monthly-mrr?...` | MRR per month `[{for, value}]` | 🟡 |
| POST | `/agency-dashboard-api/analytics/revenue/aggregate` | `{companyId, from, to}` -> total revenue | 🟡 |
| POST | `/agency-dashboard-api/analytics/reselling/revenue/aggregate` | same body, reselling revenue | 🟡 |
| POST | `/agency-dashboard-api/analytics/mrr/total` | same body, daily SaaS + reselling MRR (`saasFinalMrr`, `resellingFinalMrr`, `saasPlanWiseMrr`, `resellingProductWiseMrr`) | 🟡 |
| POST | `/agency-dashboard-api/rebilling/<companyId>/revenue/aggregate` | `{entityType:"LOCATION", from, to}` -> `{transaction_count, total_amount}` | 🟡 |

Gotchas: `from`/`to` are `YYYY-MM-DD`, timezone `Etc/GMT0` in the capture. Related: `GET services/saas_service/connect/retrieve_account?account_id=<acct>&companyId` -> `{account, balance}` (🟡 304).

## feature-permissions

Per-location feature access (SaaS plan features). Good for "why can't this sub-account see X".

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/feature-permissions/rbac/locations/<loc>/permissions` | `{data:{locationId, directPermissions:[...], featureIds:[...], dateUpdated}}` (74 each in the capture) | 🟡 |
| GET | `backend/feature-permissions/features/list` | catalogue of 74 features: `{featureId, featureName, moduleName, categoryName, featureType:"saas_product", permissions, recommendedPlanLevel, isActive}` | 🟡 |

Body note: permission strings look like `category:marketing.module:email-marketing.feature:email-marketing.permission:admin`.

Related flags (same purpose, different service): `GET services/labs/feature-flags/location/<loc>?includeExplicitOptIns=true` -> `{featureFlags:{company:{...}, location:{...}}}` (🟡); `GET services/labs/feature-flags/company/<companyId>` (🟡, 401 `LABS_UNAUTHORIZED` for account-type tokens).

## custom-menus

Agency custom menu links (left-nav links, usually iframes).

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/custom-menus/?companyId=<companyId>&showOnCompany=true&skip=0&limit=100[&locationId=<loc>]` | `{customMenus:[{id, title, url, icon:{name, fontFamily}, order, userRole, showOnCompany, showOnLocation, showToAllLocations, locations:[], excludeLocations:[], openMode, allowCamera, allowMicrophone}], totalLinks}` | 🟡 |

Notes: `openMode` was always `iframe`; `userRole` `all` (46) or `admin` (1). No writes captured.

## integrations

Connection status for Facebook and Google Business Profile. Cheap audit checks.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/integrations/facebook/<loc>/connection` | `{connected, newConnection, scopes:[{scope, targetIds}], ownerId}` | 🟡 |
| GET | `backend/integrations/gmb/oauth/scope/check?locationId=<loc>` | `{businessScopeExist}` when connected | 🟡 |

Gotchas: GBP not connected comes back as an error, not `false`: 400 or 404 `Could not find GBP integration for location Id: <loc>`. Treat 400/404 as "not connected". Facebook `scopes` lists Meta permissions (pages_messaging, leads_retrieval, whatsapp_business_messaging, ...), handy for "why are FB leads not arriving".

## marketplace

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/marketplace/core/search/module?locationId&companyId&type=triggers\|actions&skip=0&limit=200&isInstalled=true&query=<text>` | installed marketplace apps offering workflow triggers or actions: `[{appId, name, companyName, isPaid, isInstalled, triggers\|actions:[{templateId, key, version, customVars, info}]}]` | 🟡 |
| GET | `services/marketplace/custom-script/<companyId>` | agency custom scripts `{success, scripts:[]}` | 🟡 |
| POST | `backend/marketplace/billing/usage/meters/public` | `{locationId, companyId, appIds:[...]}` -> usage meters | 🟡 |

Gotcha: `core/search/module` is what the workflow builder's trigger/action picker calls (WF origin, 2021-04-15). Useful to explain third-party steps in a workflow audit.

## copilot (Ask AI)

GHL's in-app "Ask AI" assistant. One capture recorded a real session (creating a Conversation AI bot). It runs Claude Sonnet 4.6 via `anthropic-vertex` and uses tools `read_skill`, `read_artifact_skill`, `render_artifact` and `web_fetch`.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `services/copilot/ask-ai/locations/<loc>/users/<userId>/sessions?limit=50` | session list `{sessions:[{sessionId, title, provider, model, type, createdAt, updatedAt, ...}]}` | 🟡 |
| GET | `services/copilot/ask-ai/company/<companyId>/users/<userId>/sessions?limit=50` | agency-level session list | 🟡 |
| GET | `services/copilot/ask-ai/sessions/<companyId>/<sessionId>` | full transcript `{header:{...}, entries:[{type:"message"\|"artifact", turnGroupId, message:{role:"user"\|"assistant"\|"toolResult", content:[...]}}]}` | 🟡 |
| POST | `services/copilot/ask-ai/stream` | send a turn, reply as `text/event-stream` | 🟡 |
| GET | `services/copilot/ask-ai/scheduled-tasks?companyId&userId&locationId` | `{tasks:[]}` | 🟡 |
| GET | `services/copilot/ask-ai/connector-config?userId&locationId&companyId` | `{apps:[], browserControlEnabled}` | 🟡 |
| GET | `services/copilot/ask-ai/dictation/info` | voice input config | 🟡 |
| GET | `services/copilot/ask-ai/dispatch/channels?companyId&locationId&limit=100` | `{items:[]}` | 🟡 |

Body / response notes:
```json
POST /copilot/ask-ai/stream
{"message": "Approved: <title>", "locationId": "<loc>", "provider": "anthropic", "model": "claude-sonnet-4-6",
 "sessionId": "<uuid>", "companyId": "<companyId>", "userId": "<userId>", "timezone": "<tz>",
 "contactId": "<id>", "contactName": "<name>", "browserControlEnabled": true,
 "artifactResponse": {"toolCallId": "<id>", "component": "approval", "artifactId": null, "answers": {"approved": true, "title": "<title>"}}}
```
SSE event names: `run:start`, `turn_group:start`, `turn:start`, `thinking:start|delta|end`, `message:delta`, `message:toolcall`, `tool:start`, `tool:end`, `message:end` (usage and cost), `artifact:start`, `artifact:data`, `turn:end`, `run:end`.

Gotchas:
- Ask AI writes go through `web_fetch` to `proxy://public/<path>` with auth injected, and only after the user clicks an `approval` artifact. The HAR shows the proxy path, not the real host.
- Its Conversation AI skill reveals the bot API: `GET /ai-employees/employees/search?locationId&limit=20[&allowedSubType=AI_EVAL_AGENT]` and `POST /ai-employees/employees`. The create body uses `employeeName` (not `name`), `isPrimary`, `waitTime`, `waitTimeUnit` (`seconds|minutes`), `mode` (`off|suggestive|auto-pilot`), and `channels` from `GMB, IG, FB, SMS, WebChat, WhatsApp, Live_Chat, Email` (case-sensitive), plus `businessName, personality, goal, instructions, sleepEnabled, sleepTime, sleepTimeUnit, autoPilotMaxMessages, respondToImages, respondToAudio, knowledgeBaseIds`. The host behind `proxy://public` is not visible: confirm with a HAR of the Conversation AI settings page before scripting.
- Other Ask AI sub-skill ids (hints at what the API supports): conversation-ai--get-agent, update-agent, delete-agent, list-actions, create-action, update-action, delete-action, update-followup-settings, conversation-logs, fetch-dashboard-data, get-generation-details, onboarding.
- 403 `Forbidden resource` on sessions / scheduled-tasks for some accounts: Ask AI is not enabled there.

## ai-wrapper, ai-employees, agent-studio

AI plan and feature-gate checks. Useful in audits ("is AI Employee on, which plan").

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `services/ai-wrapper/plan/location?locationId=<loc>` | `{plan:{type, currency}, effectivePlanType, productEnabled, hasOptedInToCurrentPromo, isEligibleForOptIn, subscriptionExclusions}` (seen: `USAGE`, enabled) | 🟡 |
| GET | `services/ai-wrapper/plan/company?companyId=<companyId>` | agency AI plan and promo config | 🟡 |
| GET | `backend/ai-employees/beta/<loc>?feature=flow_builder` | `{isAllowed}` gate, called by the workflow builder | 🟡 |
| GET | `services/agent-studio/agents?locationId&agencyId&productId=agent_studio&limit&offset` | Agent Studio agents `{agents:[], pagination:{total, limit, offset, hasMore}}` | 🟡 |

## internal-tools (agency billing)

Mostly app chrome. One call is audit-worthy.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/internal-tools/billing/company/<companyId>/plan` | the agency's own GHL subscription: `{amount, currency, cycle, status, currentPeriodEnd, cancelAt, subscription:{...}}` | 🟡 |
| GET | `backend/internal-tools/billing/company-info/<companyId>` | billing address, card brand/last4, tax status | 🟡 |

Gotchas: 401 `You are not authorised to access this scope!` for account-type tokens. `company-info` holds card and address data: never dump it into reports.

## notifications

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend/notifications/users/<userId>?limit=25&skip=0&deleted=false` | bell notifications `{notifications:[{type, notificationData:{subType, status, locationId, snapshotId, title, body}, read}]}` | 🟡 |

Note: types seen include email, sms, voicemail, task summaries and `snapshot` / `snapshot_push_completed`. That last one is a cheap way to confirm a snapshot push finished. The response is base64 in some HARs.

## Noise

App chrome, upsell and tracking. Nothing to script:
- `onboarding/*` (version, reward-enum, widget-info, track/events, affiliate/attribution): onboarding wizard and analytics events.
- `launchpad/segments/*` on backend: `{segmentAssigned}` flag.
- `affiliate-portal/<companyId>`, `affiliate-manager/<loc>/location-customization`: GHL affiliate programme.
- `reselling/configuration/location/<loc>/{CP_BRANDED_APP_49, seo_search_atlas, Prospecting}`, `reselling/subscription/location/<loc>`, `ad-publishing/reselling/configuration/location/<loc>`: reselling upsell offers (mostly 304).
- `saas-billing-v2/billing-config/{COMPANY|LOCATION}/<id>[/conversationAI|conversation_AI|contentAI|domainPurchase|workflow_premium_actions]`: rebilling/markup config per product. Note both `conversationAI` and `conversation_AI` spellings are live. Only useful if auditing AI rebilling markup.
- `internal-tools/billing/implementation-modal-count`, `internal-tools/compliance/get-hipaa-detail/<companyId>`, `internal-tools/compliance/hipaa-outreach/<companyId>/<userId>`.
- `saas_service/isv-mode/status/<loc>`: LC Phone ISV status, 422 `Twilio Account not found` when the location has no Twilio account.
- `appengine/google/get_views` (Google Analytics views, mostly 400) and `appengine/search/contact/all` (raw Elasticsearch contact search used by the email builder's test-contact picker; use the contacts endpoints instead).
- `labs/feature-flags/*` beyond the debugging use noted above.
- Third party, not GHL: `customizerapi.locationapi.co/{login, agency, agency_connection, locations, launchpad/*, alertpopups}` (origin `cp.modalsupport.com`, an agency "customizer" add-on loaded by an agency's custom JS; its `login` is `{ref_key, domain_name}` and has nothing to do with GHL auth), `auth.locationapi.co`, `/_pm/*` on the whitelabel host, `featureassets.org` / `prodregistryv2.org` (Statsig), `api.canny.io`, `commsmessenger.com`, google-analytics.
- `services/locations/undefined/customFields|customValues` (status 0) and the token-less shell GETs of `services/locations/<loc>/customFields|customValues`: page-load prefetch, some with odd params (`?hvac=7`), 401 `Error calling IAM service` when its hidden auth is missing. Not a pattern to copy: toolkit scripts call these with `token-id` and work.

---

# 2. Workflows, CRM, calendars, phone

Scope: domains `workflow`, `workflows`, `workflows-marketplace`, `calendars` (additions only), `locations` and `locations/*`, `custom-fields`, `custom-data`, `objects`, `associations`, `businesses`, `contacts`, `conversations`, `opportunities`, `products`, `payments`, `phone-system`, `cpaas`, `firebase-firestore`, `firebase-firebasestorage`.
Placeholders: `<loc>` location id, `<wf>` workflow id, `<tid>` trigger id, `<cid>` contact id, `<company>` company id, `<id>` any other id.
Status: 🟡 = a 2xx (or a 304 replay of one) seen in a capture, ⚠️ = only errors seen. Nothing here was run live.

## Corrections (read first)

1. **Trigger create URL.** Some notes show `POST /workflow/{loc}/trigger?workflowId={wf}`. Every capture that creates a trigger POSTs to `/workflow/<loc>/trigger` with **no query string** and `workflowId` in the body.
2. **Trigger `active` flag.** Scripts often send `active:false`. The UI always sends `active:true` together with `status:"draft"` and `triggersChanged:true`. `active:false` is still the safe choice for script-built drafts, but it is not what the UI does, so a UI-made trigger reads back `active:true` on a draft workflow.
3. **Trigger body keys.** Older trigger examples use top-level `workflow_id` and omit `status`, `triggersChanged`, `masterType`. The real body uses `workflowId` (camelCase) at top level, `masterType:"highlevel"`, and `workflow_id` only inside `actions[]`.
4. **The UI binds a new trigger with a second call.** After `POST /trigger` the UI immediately PUTs the whole workflow plus `newTriggers` (newer captures: `PUT /workflow/<loc>/only-triggers/<wf>`; older ones: `PUT /workflow/<loc>/<wf>/auto-save`). That PUT bumps `version` and writes a new `triggersFilePath` (the per-version trigger snapshot). A POST alone is enough for live behaviour (readback works), but a POST-only script leaves the version history without a trigger snapshot for that change (inference from the response fields).
5. **Version history endpoint.** `GET /workflow/<loc>/<wf>/history` lists versions (`fileUrl` per version). The UI also uses `GET /workflow/<loc>/<wf>/history-by-number/<n>`, which returns one version with the body **inline** (`workflowData.templates`) and **`triggersData`** (the trigger set at that version). That is the only place past trigger configs are visible.
6. **Calendar `version` header.** Calendar APIs are often documented with `version: 2021-04-15`. Every calendar call in a calendar-build capture (GET, POST, PUT) sends `version: 2021-07-28` with `origin: https://calendar-app.leadconnectorhq.com`. The 04-15 value also works (scripted calendar builds succeed with it), so this is a "mirror the UI if you hit a 4xx" note.
7. **Custom field host and fieldKey.** It is easy to assume everything is on `backend.` and that `fieldKey` derives from `name`. In captures every custom field and folder **create** goes to `services.leadconnectorhq.com` with `version: 2021-07-28`, and the survey builder sends an explicit `fieldKey` (no `contact.` prefix) that the server stores as `contact.<fieldKey>`. So fieldKey can be chosen.
8. **`version` header is optional on builder endpoints.** The UI sends no `version` header on `POST /trigger`, `PUT .../auto-save`, `PUT .../only-triggers`, `POST .../validate-assets`, `GET .../history-by-number`, `GET .../error-notification` (one capture also had no `source`). `ghl.sh`'s `2021-04-15` is harmless; just do not treat a missing header as the cause of a failure there.
9. **Base64 bodies.** Some response bodies are stored with `content.encoding == "base64"` in a HAR (e.g. the WhatsApp template list and `workflows-marketplace/.../assets`), so a naive parser sees no body. Base64-decode them. 304 responses also carry the cached body in these HARs.

## workflow (builder API, `backend.leadconnectorhq.com/workflow/<loc>/...`)

What the workflow builder calls on open, on trigger add and on auto-save. Origin `https://client-app-automation-workflows.leadconnectorhq.com`.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `/workflow/<loc>/validate-assets` | Pre-save check of the canvas: `{templates, triggers, companyId}` → `{errors:[], warnings:[]}` | 🟡 |
| POST | `/workflow/<loc>/trigger` | Create a trigger (body below) → `{id}` | 🟡 |
| PUT | `/workflow/<loc>/only-triggers/<wf>` | Save trigger changes: full workflow doc + `triggersChanged:true` + `newTriggers` | 🟡 |
| PUT | `/workflow/<loc>/<wf>/auto-save` | Builder auto-save: full workflow doc + `isAutoSave:true` + `autoSaveSession` (+ `newTriggers` when triggers changed) | 🟡 |
| GET | `/workflow/<loc>/<wf>/history-by-number/<n>` | One saved version, body inline + `triggersData` | 🟡 |
| GET | `/workflow/<loc>/auto-save/settings` | Is builder auto-save on for the location: `{_id, locationId, isActive, updatedBy, createdAt, updatedAt}` | 🟡 (304) |
| GET | `/workflow/<loc>/workflow-location-setting/settings` | Location-level workflow settings; `{}` on every capture (nothing set) | 🟡 (304) |
| GET | `/workflow/<loc>/workflow-ai/settings` | Workflow AI settings; `{}` | 🟡 (304) |
| GET | `/workflow/<loc>/error-notification/<wf>` | Per-workflow error-notification config; `null` when unset. Write not captured | 🟡 (304) |
| GET | `/workflow/<loc>/email/location-email-provider` | Sending provider for email steps (answers 201 on a GET) | 🟡 |
| GET | `services.../workflow/<loc>/instagram/connected-accounts?unique=true` | FB/IG pages connected, for IG/FB steps: `{pages:[{facebookPageId, facebookPageName, instagramPageId, instagramUsername, syncType, connectionType}], isConnected, isMappingsCompleted, total}` | 🟡 |
| GET | `/workflow/<loc>/<wf>?includeScheduledPauseInfo=true&sessionId=<uuid>` | The normal body GET; the UI adds a client-generated `sessionId` | 🟡 |
| GET | `/workflow/<loc>/trigger?workflowId=<wf>` | Trigger list for one workflow (array: `id, name, type, active, conditions, actions, masterType, schedule_config, belongs_to, workflow_id, location_id, date_added, date_updated, deleted`) | 🟡 |
| GET | `/workflow/<loc>/list?status=published&sortBy=name&sortOrder=asc&search=&limit=20&offset=0` | Workflow list with `status` and `search` filters → `{rows, count, isLocationRateLimited}` | 🟡 |

### Body / response notes

Trigger create, exactly as the UI sends it (tag trigger; contact_changed is the same with `type:"contact_changed"` and a `has-changed` condition):

```json
POST /workflow/<loc>/trigger
{"status":"draft","workflowId":"<wf>","schedule_config":{},
 "conditions":[{"operator":"index-of-true","field":"tagsAdded","value":"<tag name, lowercase>",
                "title":"Tag added","type":"select","id":"tag-added"}],
 "type":"contact_tag","masterType":"highlevel","name":"<trigger name>",
 "actions":[{"workflow_id":"<wf>","type":"add_to_workflow"}],
 "active":true,"triggersChanged":true,"location_id":"<loc>","company_id":"<company>","company_age":41}
→ {"id":"<tid>"}
```

contact_changed condition as sent: `{"operator":"has-changed","field":"contact.<fieldId>","title":"<Field name>","type":"numerical","id":"<fieldId>"}` (`type` = the field's data type).

Trigger-only save (sent right after the POST):

```json
PUT /workflow/<loc>/only-triggers/<wf>
{ ...every field of the GET ?includeScheduledPauseInfo doc (_id, locationId, companyId, companyAge, name,
  version, dataVersion, allowMultiple, timezone, removeContactFromLastStep, filePath, fileUrl, stopOnResponse,
  autoMarkAsRead, permission, type, meta, createdAt, updatedAt, deleted, creationSource,
  isTriggerBucketMigrated, originType, __v, allowMultipleOpportunity, eventStartDate, parentId,
  workflowNote, status, triggersFilePath, updatedBy, id, workflowData:{templates}, permissionMeta,
  scheduledPauseDates),
  "modifiedSteps":[], "deletedSteps":[], "createdSteps":[], "senderAddress":{},
  "triggersChanged":true,
  "newTriggers":[{ <the trigger body above>, "id":"<tid from the POST>" }] }
→ the workflow doc, version +1, filePath unchanged (still .../workflows/<wf>/<old n>),
  triggersFilePath = "location/<loc>/workflow-triggers/<wf>/<new version>"
```

Rule of thumb: `version` greater than the `filePath` number means a trigger-only save.

Auto-save is the same doc plus:

```json
"isAutoSave": true,
"autoSaveSession": {"workflowId":"<wf>","id":"<uuid>","userId":"<user>","version":2,"inProgress":true}
→ filePath = "location/<loc>/workflows/<wf>/auto-save-<epoch ms>", autoSaveSessionId = "<uuid>"
```

`history-by-number/<n>` response (trimmed):

```json
{"_id":"<wf>-17","id":"<wf>-17","workflowId":"<wf>","version":17,"status":"published","name":"...",
 "filePath":".../workflows/<wf>/17","triggersFilePath":".../workflow-triggers/<wf>/15",
 "allowMultiple":true,"stopOnResponse":false,"parentId":"<folder>","workflowNote":{...},"updatedBy":"<user>",
 "workflowData":{"templates":[...]},
 "triggersData":[{"id":"<tid>","name":"...","type":"contact_changed","active":true,"status":"draft",
                  "conditions":[...],"actions":[...],"belongs_to":"workflow","date_updated":"..."}]}
```

`email/location-email-provider` → `{provider:{domain, apiKey, domainOwnershipType:"location_owned", warmupInfo:{warmupStage, warmupStatus:"in_progress", warmupMode}}, type:"leadconnector", applyRateLimit}`.

### Call sequences seen

**Add a tag trigger to a draft:** open trigger panel → `GET marketplace/core/search/module?type=triggers` + `GET /calendars/configuration/location/<loc>` + `GET /locations/<loc>/tags` → type in tag box → `GET /locations/<loc>/tags/search?query=<text>&limit=30&skip=0` → `POST validate-assets` → (rename trigger) `POST validate-assets` again → Save trigger → `POST /trigger` → `PUT /only-triggers/<wf>`.
**Add a contact_changed trigger:** same panel loads → `POST /trigger` → `PUT /<wf>/auto-save` with `newTriggers`.
**Open a workflow in the builder:** `workflow-ai/settings`, `instagram/connected-accounts`, `workflow-location-setting/settings`, `workflows-marketplace/integration-apps`, `auto-save/settings` → `GET /<wf>?includeScheduledPauseInfo=true&sessionId=` → `GET /trigger?workflowId=` + `GET /workflows/sticky-notes-all` → `tags`, `users/search`, `email/location-email-provider`, `customFields/search?model=contact`, `workflows-marketplace/location/<loc>/assets`, `custom-data/conversations`, `customFields?model=opportunity`, `associations/objectKey/contact`, `objects/business` → `workflows/status/search/count-per-step`.

### Gotchas

- `only-triggers` and `auto-save` take the **full workflow document**, so treat them like the main PUT: build from a fresh GET, never a partial body. Untested whether they clobber omitted fields, assume they do.
- An auto-save repoints `filePath`/`fileUrl` to an `auto-save-<ms>` file. Anything that reads the body from `fileUrl` reads the auto-saved draft.
- `validate-assets` returned empty `errors`/`warnings` both times; the error shape is unknown.
- `email/location-email-provider` returns the sending domain's Mailgun API key in clear text. Never log or copy it.
- The builder also writes a presence heartbeat to Firestore every ~60 s (see Firestore section); it is not a save.

## workflows (enrolment status and execution logs)

The Execution Logs tab. Two-level: enrolments (one per contact run) then the step events of one enrolment.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/workflows/status/search/workflow-with-filter?workflowId=<wf>&locationId=<loc>&action=first&limit=51[&contactId=<cid>]` | Enrolment list, newest first, optional contact filter | 🟡 |
| GET | `/workflows/logs/v2?locationId=<loc>&workflowId=<wf>&executionId=<statusId>&limit=1000` | Every step event of one enrolment | 🟡 |
| GET | `/workflows/logs/v2?...&executionId=<statusId>&limit=51&action=first&dateType=custom&fromDate=<ms>&toDate=<ms>` | Same, with a date window | 🟡 (304) |
| GET | `/workflows/status/search/count-per-step`, `/workflows/sticky-notes-all` | Already documented | 🟡 |

### Body / response notes

```json
workflow-with-filter →
{"statuses":[{"_id":"<statusId ULID>","id":"<statusId>","sid":"<id>","contactId":"<cid>","workflowId":"<wf>",
   "enrollType":"workflow","status":"finished|wait_time","currentStepId":"<step>","currentStepName":"Email - Feedback",
   "currentStepType":"email","executeOn":"...","waitingFor":"contact_<cid>","sequence":2,
   "meta":{"addedSource":{"source":"trigger","channel":"trigger","sourceName":"<trigger name>",
                          "triggerType":"contact_changed","id":"<tid>"}},
   "createdAt":"...","updatedAt":"..."}],
 "count":46,"isLocationRateLimited":false}
```

```json
logs/v2 → [ {"type":"email","status":"success","stepId":"<step>","stepName":"...","sequence":2,
   "workflowStatusId":"<statusId>","timestamp":"...","nextExecutionAt":null,
   "contactId":"<cid>","contactName":"<name>","contactEmail":"<email>",
   "meta":{"version":16, "data":{"messageId":"<id>","conversationId":"<id>","msg":"Email queued successfully."}, ...},
   "metrics":{"actionExecutionTime":765,"segments":[{"name":"POST-/:id/messages","value":703}]}}, ... ]
```

Event `type`/`status` pairs seen: `added_to_workflow/added_to_workflow` (meta.addedSource = which trigger), `condition/success`, `email/success`, `email/waiting`, `wait/skipped`, `wait_finished/wait_finished`, `event_start_date/skipped`, `remove_from_workflow/finished|skipped` (meta.removedFrom.type `end_of_workflow`).
Useful meta: `meta.version` = the workflow version that ran (pair with `history-by-number/<version>`); `meta.skippedFor = {type:"missing-data"|"invalid-date", msg}` says why a wait or event-date step was skipped; condition events carry `isQualified`, `branches` and `trace: [[{index, conditions:[{existingValue, conditionOperator, conditionValue, result}]}]]`, i.e. the contact's actual value at evaluation time.

### Call sequence

1. Open Execution Logs → `workflow-with-filter?action=first&limit=51`.
2. UI hydrates names → `POST /contacts/search/2` `{locationId, page:1, pageLimit:N, sort:[], filters:[{field:"id", operator:"eq", value:[<cid>,...]}]}`.
3. Contact filter box → per keystroke `POST /contacts/search/2` with the generic filter (contacts section) → pick → `workflow-with-filter ...&contactId=<cid>`.
4. Expand a run → `logs/v2?executionId=<statusId>&limit=1000`.
5. `GET /workflow/<loc>/error-notification/<wf>` also fires on this tab.

### Gotchas

- `executionId` is the enrolment `_id` from `workflow-with-filter` (a ULID), not a contact id.
- The UI asks `limit=51`; next-page parameters were not captured (`action=first` suggests `action=next` plus a cursor).
- Log events include contact name and email: redact before saving anywhere.
- This is the scriptable answer to "why did this contact skip/branch": read `skippedFor` and the condition `trace` instead of guessing.

## workflows-marketplace

Catalogues of marketplace-defined workflow actions and triggers.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/workflows-marketplace/integration-apps?locationId=<loc>` | Installed marketplace apps usable in workflows (15 here): `appId, appName, key, logo, isActive, rateLimit, locationIds, companyIds` | 🟡 (304) |
| GET | `/workflows-marketplace/location/<loc>/assets?workflowTypes=default,contacts` | Every marketplace action and trigger definition: `{actions:[{appName, actions:[...]}], triggers:[{appName, triggers:[...]}]}` | 🟡 |

### Body / response notes

Each action has `key, inputs (field schema), executionConfig, customVars, conditions, section, workflowsActionType, saveResponse, waitForReply`. Keys seen include `whatsapp_v2`, `send_whatsapp_message`, `whatsapp_24h_window`, `internal_create_opportunity`, `internal_update_opportunity`, `find_opportunity`, `task-notification`, `lc_merge_contact`, `contact_email_verification`, `payments_create_invoice`. Trigger keys include `task_completed`, `service_booking`, `rental_booking`, `quiz_submitted`, `messaging_errors`, `funnel_website_pageview`, `subscription`, `refund`, `coupon_code_redeemed`.

### Gotchas

- Core actions (email, sms, if_else, wait, add_contact_tag) are not in this catalogue; it only covers marketplace/app-defined ones. Use it to get exact `type` keys and input names before building one of those steps.
- Stored base64 in the HAR (decode before parsing).

## firebase-firestore and firebase-firebasestorage

Firestore (`firestore.googleapis.com/google.firestore.v1.Firestore/Listen/channel` and `/Write/channel`, project `highlevel-backend`) is the realtime side channel: presence, bell notifications, release notes, permissions, and a few legacy mirrors. No workflow, contact, opportunity or custom-field data travels through it in any capture.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST/GET | `.../Listen/channel?database=projects/highlevel-backend/databases/(default)` | WebChannel long-poll: POST adds watch targets, GET streams documentChange events | 🟡 |
| POST/GET | `.../Write/channel?database=.../(default)` | WebChannel writes | 🟡 |
| POST/GET | `.../Listen/channel?database=.../feature-permissions` | `features` query and `rbac_location_permissions/<loc>` doc | 🟡 |
| POST/GET | `.../Listen/channel?database=.../leadgen-onboarding-production` | `launchpad_progress` (refId, deleted) | 🟡 |
| GET | `firebasestorage.googleapis.com/v0/b/highlevel-backend.appspot.com/o/location%2F<loc>%2Femails%2F<tid>%2Findex.html?alt=media&token=<t>` | Compiled HTML of an email-builder template | 🟡 |

### What the app watches ((default) database)

- Documents: `companies/<company>`, `locations/<loc>`, `users/<user>`, `domains/<id>`, `funnels/<id>`.
- Queries: `notifications` (user_id ==, order date_added, limit 1), `app_release` and `app_release_ignore_list` (release-note popups), `mailgun_accounts` (company_id or location_id ==), `twilio_accounts` (location_id ==), `calendars` and `teams` (location_id ==, deleted == false; snake_case legacy mirror of calendars), `funnel_pages` (location_id, funnel_id, deleted), `editor_active_viewers` (location_id ==, plus `alt_id ARRAY_CONTAINS "workflow_<wf>"` or `["funnel_<id>","page_<id>"]`).

### Writes seen

- `editor_active_viewers/<id>`: presence. The workflow and funnel builders rewrite `active_users[]` (user id, first/last name, email, phone, photo, date_update) about every 60 s with `updateMask:["active_users"]`; first open creates the doc with `location_id`, `alt_id`, `deleted`, dates.
- `funnel_pages/<pageId>`: the funnel page **SEO meta** save: `update.fields.meta = {title, description, keywords, author, imageUrl, customMeta[], canonicalMeta[], language}`, `updateMask:["meta"]`, `currentDocument.exists:true`. No REST call carried it in the capture.

### Is anything only readable here?

- **Who is editing a workflow or funnel right now** (`editor_active_viewers`). Only in Firestore. Handy before an API PUT on a live workflow, if Firestore reads are ever scripted.
- **Funnel page SEO meta writes** go through Firestore only (reads probably also come back via REST page data; not checked).
- Everything else mirrors REST (`locations`, `users`, `companies`, `calendars`). The `locations` doc holds sensitive keys (`api_key`, `facebook_page_token`, `stripe`); `companies` holds billing and Stripe ids.
- Workflow bodies are not in Firestore: they are Firebase **Storage** files in bucket `automation-workflows-production` (`location/<loc>/workflows/<wf>/<n>`, triggers at `.../workflow-triggers/<wf>/<n>`).

### Gotchas

- The captures never show the channel handshake, so how the Firebase idToken is attached is not visible. Scripting Firestore is untested; use REST wherever it exists.
- `twilio_accounts` and `mailgun_accounts` are queried but no documents came back in any capture.

## locations/customFields and custom-fields (folders, opportunity fields, conditional rules)

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `services.../locations/<loc>/customFields` `{documentType:"folder"}` | Create a custom-field folder | 🟡 |
| POST | `services.../locations/<loc>/customFields` `{documentType:"field", parentId}` | Create a field inside a folder | 🟡 |
| GET | `backend.../locations/<loc>/customFields/search?parentId=&skip=0&limit=10000&documentType=folder&model=all&query=&includeStandards=true` | All folders, all models | 🟡 |
| GET | same with `documentType=field` (or `&model=contact|opportunity`) | All fields incl. standard ones, with `parentId` | 🟡 |
| GET | `backend.../locations/<loc>/customFields?model=opportunity` | Opportunity custom fields | 🟡 |
| GET | `services.../custom-fields/conditional-fields/list?locationId=<loc>&objectKey=opportunity&limit=1000` | Conditional show/hide rules for an object's fields | 🟡 |
| GET | `backend.../custom-fields/object-key/business?locationId=<loc>` | Company (business) fields and folders | 🟡 |

### Body / response notes

```json
POST services.../locations/<loc>/customFields      (version 2021-07-28)
{"documentType":"folder","model":"contact","name":"<folder name>"}
→ 201 {"customFieldFolder":{"id":"<folderId>","model":"contact","name":"...","position":600,
        "documentType":"folder","locationId":"<loc>","standard":false,"scopes":[]}}

{"name":"<field name>","fieldKey":"my_rating","dataType":"NUMERICAL","documentType":"field",
 "showInForms":true,"model":"contact","parentId":"<folderId>","description":""}
→ 201 {"customField":{"id":"<id>","fieldKey":"contact.my_rating","parentId":"<folderId>","position":50,...}}
```

Folder search → `{customFieldFolders:[{id, name, model, position, fieldsCount, standard?, standardFieldsFolder?, originId?}], totalItems}`. Standard folders seen: "Contact" (contact), "Opportunity Details" (opportunity). Field search → `{customFields:[{id, name, fieldKey, dataType (incl. STANDARD_FIELD), model (contact|opportunity|business), parentId, position, standard, picklistOptionsImage}], totalItems}`.

Conditional rules:

```json
{"rules":[...],"systemRules":[{"objectKey":"opportunity",
  "filters":[{"group":"AND","filters":[{"field":"status","operator":"any_of","value":["lost"],
     "extras":{"uiVersion":1,"uiFieldKey":"status","uiFieldType":"MULTIPLE_OPTIONS","uiOperator":"any_of"}}]}],
  "outcomes":[{"type":"show_field","targetKey":"custom_fields.lost_reason"}],
  "conditionFieldKeys":["status"],"outcomeTargetKeys":["custom_fields.lost_reason"],
  "outcomeFolderIds":[],"active":true,"system":true}],"total":1}
```

### Gotchas

- `services.../locations/<loc>/customFields` with no `model` returns **contact fields only** (131 contact fields in one capture, zero opportunity). Ask `backend.../customFields?model=opportunity` or the search with `model=opportunity` for opportunity fields.
- Folder `position` is auto-assigned in steps of 100 (500, 600); field position in steps of 50.
- Moving an existing field into a folder was not captured (custom values use a PUT with `parentId`; the same probably works for fields, untested).
- Conditional-rule create/edit was not captured, only the list. The one system rule shows Lost Reason when status is lost.

## locations/customValues and custom-data (merge-tag pickers)

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend.../locations/<loc>/customValues/search?skip=0&limit=25&query=&getCount=true` | Paged custom values with folders (`fieldsCount`) and `total` | 🟡 |
| GET | `backend.../custom-data/conversations?locationId=<loc>&types=custom-values` | Merge-tag tree for workflow/conversation editors | 🟡 |
| GET | `backend.../custom-data/emails?locationId=<loc>&types=custom-values` | Same tree for the email builder (headers `internal-channel: email-builder`, `location-id: <loc>`) | 🟡 |
| GET | `backend.../custom-data/funnels?locationId=<loc>&types=custom-values` | Same tree for funnels | 🟡 |

### Body / response notes

```json
{"for":"conversations",
 "static":[{"label":"Account","value":"__account__","children":[{"label":"Name","value":"{{location.name}}"}, ...]},
           {"label":"Appointment","value":"__appointment__","children":[{"label":"Start Date Time","value":"{{appointment.start_time}}"}, ...]},
           {"label":"Attribution", ... "{{ contact.attributionSource.sessionSource }}", "{{ contact.lastAttributionSource.url }}" ...}],
 "custom-values":[{"label":"<folder>","value":"{{ <folderId> }}","meta":{"id":"<folderId>","fieldsCount":7,"documentType":"folder"},
                   "children":[{"label":"Business Name","value":"{{ custom_values.business_name }}",
                                "meta":{"id":"<id>","parentId":"<folderId>","value":"<current value>"}}]}]}
```

### Gotchas

- This is the authoritative list of merge tags each builder offers, including attribution and appointment tags; use it to validate `{{...}}` strings in API-built steps.
- `children[].meta.value` carries the live custom value (can include staff emails and phones).
- Calls to `/locations/undefined/customValues?hvac=7` and `/locations/undefined/customFields` (status 0) are a UI race before the location id resolves. Noise.

## locations/tags (rename, categories, search)

| Method | Path | What it does | Status |
|---|---|---|---|
| PUT | `backend.../locations/<loc>/tags/<tagId>` | Rename / recolour / categorise a tag | 🟡 |
| GET | `backend.../locations/<loc>/tags/categories` | Tag categories (folders) and uncategorised count | 🟡 |
| GET | `backend.../locations/<loc>/tags/search?skip=0&limit=100&query=&getCount=true&sortBy=dateUpdated&sortOrder=desc` | Tags page list | 🟡 |
| GET | `backend.../locations/<loc>/tags/search?query=<text>&limit=30&skip=0` | Typeahead in the trigger/action tag picker | 🟡 |
| GET | `backend.../locations/<loc>/tags` | Full list, loaded when the trigger panel opens | 🟡 |

### Body / response notes

```json
PUT /locations/<loc>/tags/<tagId>          (version 2021-07-28)
{"name":"New Tag Name","categoryId":null,"color":"#475467","description":""}
→ {"tag":{"id":"<tagId>","name":"new tag name","categoryId":null,"description":null,"color":"#475467"}}

GET tags/categories → {"categories":[],"uncategorized":{"id":null,"tagsCount":44,"isVirtual":true},"totalCount":0}
GET tags/search     → {"tags":[{"_id","name","dateAdded","dateUpdated","color","description"}], "total":44}
```

### Call sequence

Rename in Settings > Tags: `GET tags/categories` → `PUT tags/<id>` → `GET tags/search?...sortBy=dateUpdated` (refresh). Nothing else fires.

### Gotchas

- Rename lowercases the name, same as create.
- Workflow triggers (`conditions[].value`) and add/remove-tag steps (`attributes.tags`) store the tag **name**, and the rename fires no follow-up calls, so every workflow reference keeps the old name. Rename = re-point every trigger and step (or keep the old tag). Inferred from the payloads; not tested live.
- `categoryId` exists on tags, but category create was not captured.

## objects, associations, businesses

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend.../objects/business/?locationId=<loc>&fetchProperties=true` | Company object definition plus its fields | 🟡 |
| GET | `backend.../associations/objectKey/contact?locationId=<loc>` | Association definitions involving contacts | 🟡 |
| GET | `backend.../businesses?locationId=<loc>` | Company records `{success, businesses:[]}` | 🟡 |
| GET | `backend.../objects/?locationId=<loc>` | Already documented | 🟡 |

### Body / response notes

```json
associations → {"associations":[
 {"key":"OPPORTUNITIES_CONTACTS_ASSOCIATION","associationType":"SYSTEM_DEFINED","firstObjectKey":"opportunity","secondObjectKey":"contact",
  "firstObjectToSecondObjectCardinality":"MANY_TO_MANY","firstObjectToSecondObjectMaxLimit":25,"secondObjectToFirstObjectMaxLimit":1000},
 {"key":"BUSINESSES_CONTACTS_ASSOCIATION","firstObjectKey":"business","secondObjectKey":"contact","firstObjectLabel":"Primary Company",
  "firstObjectToSecondObjectCardinality":"ONE_TO_MANY","firstObjectToSecondObjectMaxLimit":10000,"secondObjectToFirstObjectMaxLimit":1}],"total":2}
objects/business → {"object":{"labels":{"singular":"Company","plural":"Companies"},"requiredProperties":["business.name"],
  "searchableProperties":["business.name","business.email"],"primaryDisplayProperty":"business.name"},"fields":[...]}
```

### Gotchas

- Limits worth knowing: one opportunity links to at most 25 contacts, a contact to at most 1000 opportunities and 1 company.

## contacts and conversations

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `backend.../contacts/search/2` (generic filter) | Name/email/phone typeahead | 🟡 |
| POST | `backend.../contacts/search/2` (id filter) | Hydrate contacts by id list | 🟡 |
| POST | `backend.../conversations/manual-actions?locationId=<loc>` | Manual call/SMS task counters for the nav badge | 🟡 |
| GET | `backend.../conversations/providers/search?locationId=<loc>&type=custom` | Custom (marketplace) conversation providers | 🟡 |

### Body / response notes

```json
generic typeahead:
{"locationId":"<loc>","page":1,"pageLimit":10,"sort":[],
 "filters":[{"group":"OR","filters":[{"group":"AND","filters":[{"filterName":"generic","filterName_lc":"generic","extras":{},
   "selectedOption":{"filterName":"generic","filterName_lc":"generic","condition":"is","firstValue":"<text>"}}]}]}]}
by id:  {"locationId":"<loc>","page":1,"pageLimit":4,"sort":[],"filters":[{"field":"id","operator":"eq","value":["<cid>", "..."]}]}
→ {"contacts":[...],"total":N}

manual-actions body {"campaign":"","assignee":""} → {pendingCalls, pendingSms, completedCalls, completedSms, totalCalls, totalSms, lastActivity}
```

### Gotchas

- `operator:"eq"` with an **array** value works as "id in list" (duplicates allowed); handy to batch-hydrate contact ids from logs.
- The generic filter is a different shape from the `{field, operator, value}` filters `contacts_scan.py` uses; both are accepted by search/2.

## opportunities, products, payments

Only reads were captured. `GET /opportunities/pipelines` is already documented; nothing new for opportunities.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `backend.../products/public?locationId=<loc>&storeId=<id>&limit=100&offset=0&sortOrder=desc&sortField=updatedAt&prioritizeAvailable=false` | Store products for funnel order/product elements | 🟡 |
| GET | `services.../payments/integrations/<loc>` | Payment provider config per provider and mode | 🟡 |
| GET | `services.../payments/currency` | Currency catalogue (symbol, decimals, code) | 🟡 |
| GET | `backend.../payments/integrations/stripe/?location_id=<loc>` | Bare `true/false`: Stripe connected | 🟡 |
| GET | `backend.../payments/integrations/entity-providers?altId=<loc>&altType=location&includeDefault=true&entityTypes[]=calendars` | Default and express payment provider, receipt settings, for calendar payments | 🟡 |

### Gotchas

- `payments/integrations/<loc>` returns `stripe.test/live.{publishableKey, secretKey}` (and PayPal, Square, NMI, Authorize.net, Adyen blocks). Treat the whole response as secret.

## phone-system and cpaas (WhatsApp, voice)

All `backend.leadconnectorhq.com`. WhatsApp calls send `version: 2021-07-28`; voice/number calls `2021-04-15`.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/phone-system/whatsapp/location/<loc>/is-configured` | WABA linked? `{whatsAppBusinessAccountId, isConfigured, onboardingErrorMessage, mmLiteTermsSigned}` | 🟡 (304) |
| GET | `/phone-system/whatsapp/location/<loc>/account-info` | WABA review status, business verification, messaging tier | 🟡 (304) |
| GET | `/phone-system/whatsapp/location/<loc>/phone-numbers` | WhatsApp numbers: `id` (use in whatsapp_v2 steps), `displayPhoneNumber`, `status`, `quality`, `messagingLimitTier`, `default` | 🟡 (304) |
| GET | `/phone-system/whatsapp/location/<loc>/reselling/configuration` | Agency resale offer `{offeringEnabled, amount, subscriptionPeriod, productLabel}` | 🟡 (304) |
| GET | `/phone-system/whatsapp/location/<loc>/reselling/subscription` | Subscription rows `{productCode:"WHATSAPP_V1", paymentStatus, purchaseStyle, meta.agencyPaid, amount}` | 🟡 |
| GET | `/phone-system/whatsapp/location/<loc>/template` | Template list | 🟡 |
| GET | `/phone-system/whatsapp/location/<loc>/folders` | Template folders (`[]`) | 🟡 (304) |
| POST | `/phone-system/whatsapp/location/<loc>/template` | Create template (Meta template body, component shapes below) | 🟡 |
| DELETE | `/phone-system/whatsapp/location/<loc>/template/<templateId>/<templateName>` | Delete template → `{success:true}` | 🟡 |
| GET | `/phone-system/whatsapp/location/<loc>/phone-numbers-meta?fields[]=config` | Number config | ⚠️ 400 `WHATSAPP_NO_INTEGRATION_LOCATION` on locations without WhatsApp |
| GET | `/phone-system/voice-call/location/<loc>/token?userId=<user>&isNewFlow=true&reason=pageListeners` | Browser voice client token `{token, underISV}` (header `api-version: v2`) | 🟡 / 400 `no-twilio-account` |
| GET | `/phone-system/kyc-verification/compliance-check?entityId=<loc>&entity=LOCATION&rawDataNeeded=false` | `{isCompliant, isLimitExceeded, isWhitelisted}` | 🟡 |
| GET | `/phone-system/rcs/v2/senders/exists?locationId=<loc>` | `{exists}` RCS sender set up | 🟡 |
| POST | `/cpaas/numbers/selection/voice?locationId=<loc>` | Which number an outbound call would use: body `{destinationDetails:[{}]}` → `{requestedSelectorType, results:[{outcome, fromNumber, displayNumber, providerType, selectorType}], defaultDisplayNumber, defaultProviderType, isDynamic}` | 🟡 |
| GET | `/cpaas/voice/call-list/gate?locationId=<loc>` | Call-list / power-dialer gate `{available, enabled, maxLines, lineCap, holdMinutes, postCallCountdownSec, addMaxContacts}` | 🟡 |

### Body / response notes

Template list item: `{id, name, language, category, status (APPROVED|PENDING), parameterFormat:"POSITIONAL", folderId, isSystemDefined, previous_category, whatsAppBusinessAccountId, components:[...]}`. Component shapes seen:

```json
{"type":"HEADER","format":"TEXT","text":"Hello {{1}},","customVariables":["{{contact.first_name}}"],"example":{"header_text":["Adam"]}}
{"type":"HEADER","format":"IMAGE","example":{"header_handle":["<meta upload handle>"]}}
{"type":"BODY","text":"...{{1}}...","customVariables":["..."],"example":{"body_text":[["..."]]}}
{"type":"FOOTER","text":"<business name>","customVariables":[]}
{"type":"BUTTONS","buttons":[{"type":"URL","text":"Survey Link","url":"<url>","isTriggerLink":false}]}
```

### Call sequences

**Open Settings > WhatsApp:** `phone-system/numbers/location/<loc>` → `reselling/configuration` + `reselling/subscription` + `account-info` + `phone-numbers` → `is-configured` → Templates tab: `template` + `folders`.
**Create template:** template editor loads `custom-data/conversations`, `customFields/search` (contact and opportunity), `links` → `POST template` → `GET template`.
**Delete template:** `DELETE template/<id>/<name>` → `GET template` + `GET folders`.

### Gotchas

- Template delete needs both the Meta template id **and** its name in the path.
- A HEADER variable needs `example.header_text` (flat array), BODY variables `example.body_text` (array of arrays).
- The template list is stored base64 in the HAR.
- The voice token is a live credential; never save it.

## calendars (additions to CALENDARS.md)

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/calendars/configuration/location/<loc>` | Calendar modules on the location: `{subAccountConfig:{isRentalsEnabled, modules:["meetings","services","rentals"]}, migratedServicesStatus, isMigrationCompleted}` | 🟡 |
| GET | `/calendars/services/all?locationId=<loc>` | Service menu ("services" calendars) | 🟡 |
| GET | `/calendars/google-organic/rwg/merchant?locationId=<loc>` | Reserve with Google merchant link; `[]` when unused | 🟡 |

### Body / response notes

`services/all` → `{services:[{_id, name, slug, serviceDuration, serviceDurationUnit, serviceCategoryId, isVariant, variantName, isVariantsEnabled, payment:{amount}, productId, teamMembers:[{id}], isActive, isPrivate, preBuffer, postBuffer, position}]}`.

### Gotchas

- Service and service-category ids here are the values `services` / `serviceCategories` trigger conditions hold (GHL does not flag those as incomplete after a snapshot load). This is the read to build that remap.
- `configuration/location` fires every time the trigger panel opens (it decides which appointment triggers to show).
- Calendar UI sends `version: 2021-07-28` (see contradiction 6).

## locations (other location endpoints)

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `/locations/ids` | Full location docs for a list of ids: body `{ids:[<loc>,...]}` | 🟡 |
| POST | `/locations/<loc>/tasks/search` | Task list: `{limit:10, skip:0, completed:false, sortKey:"dueDate", sortDirection:1, count:true}` → `{tasks:[]}` | 🟡 |
| GET | `/locations/<loc>/labs/featureFlags` | Per-module labs flags (e.g. `emailBuilder.autosave`, `funnels.*`, `objects.bulkdelete`) | 🟡 |
| GET | `/locations/<loc>/templates?type=email&skip=0&limit=2000` | Legacy email/SMS snippets `{templates, totalCount}` | 🟡 |
| GET | `/locations/<loc>/industry` | `{industry:null}` | 🟡 |
| GET | `/locations/<loc>`, `/locations/search` | Already documented | 🟡 |

### Gotchas

- `/locations/ids` is the agency-dashboard bulk read; returns the same sensitive fields as the location doc.

## Noise

- `PUT /locations/elasticsearch/<loc>/userActivity?companyId=` (activity ping, `{success}`).
- `GET services.../locations/undefined/customValues` and `/customFields` (status 0, UI race).
- Firestore `app_release`, `app_release_ignore_list`, `notifications`, `launchpad_progress`, `features`, the `hlpt-support-widget` project, and the `editor_active_viewers` heartbeats.
- `GET /workflow/<loc>/workflow-ai/settings` and `workflow-location-setting/settings` (always `{}` so far).
- `GET /calendars/google-organic/rwg/merchant` (empty).
- `GET /conversations/providers/search?type=custom` and `POST /conversations/manual-actions` (nav badges).
- `GET /phone-system/kyc-verification/compliance-check`, `/phone-system/rcs/v2/senders/exists`, `/cpaas/voice/call-list/gate`, `/phone-system/whatsapp/.../phone-numbers-meta` 400s, `/phone-system/voice-call/.../token` 400s (all fire on every page load).
- `GET /locations/<loc>/industry`, `/locations/<loc>/labs/featureFlags`, `/payments/currency`.
- UI headers that are telemetry, not auth: `app-name`, `route-name`, `route-path`, `route-pattern`, `x-translations-lang`, `baggage` (Sentry), `developer_version`.

---

# 3. Content: funnels, forms, surveys, emails

All hosts are `backend.leadconnectorhq.com` unless marked `services.`. Every call in these domains sends `channel: APP`, `source: WEB_USER`, `token-id`, and `version: 2021-07-28`, except where a row says `2021-04-15`. No `x-*` headers are needed for writes (only `x-translations-lang: en-US` on some reads, and `x-parent-trace-context` on public form events).

Origins the UI uses (mirror them when unsure; the server has not been seen to reject another origin):

| Origin | Used for |
|---|---|
| `https://page-builder.leadconnectorhq.com` | all `/funnels/builder/*` saves and builder-load reads, `/countdown-timer`, `/funnel-ai/*` |
| whitelabel app (`https://app.<your-whitelabel>.com`) | funnel overview reads, `delete-step`, `update-settings`, `funnel-share-url`, form/survey list, create, delete, email meta GET/PUT |
| `https://leadgen-apps-form-survey-builder.leadconnectorhq.com` | form and survey save (`POST services./forms/<id>`, `/surveys/<id>`), themes, default colours |
| `https://email-home-prod.leadconnectorhq.com` | email list, folder, clone, move, delete, folder-path |
| `https://email-builder-prod.leadconnectorhq.com` | email builder data GET/POST, settings, snippets, saved elements, brand-board reads |

---

## funnels (with funnel-ai, countdown-timer, chat-widget list, order-form)

Funnel and website steps, pages and the drag-and-drop page builder. A "page delete" in the UI is a step delete. Publish is the same autosave call as Save, with `pageType: "live"`.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/funnels/funnel/fetch/<funnelId>` | Funnel doc the UI uses: `data.steps[]` (camelCase `id, name, url, pages[], sequence, type, split, controlTraffic, originId, products`), `globalSectionVersion`, `globalSectionsPath/Url`, `trackingCodeHead/Body`, `domainId`, `url` | 🟡 |
| GET | `/funnels/page/list?funnelId=<id>&locationId=<loc>` | Page docs for the funnel | 🟡 |
| GET | `/funnels/page/<pageId>` | Page doc: `pageVersion`, `versionHistory[]` (each `pageType draft/live`, `pageDownloadUrl`, `versionId`), `pageDataDownloadUrl`, `meta`, `stepId`, `url` | 🟡 |
| GET | `/funnels/builder/page/data?pageId=<id>` | Builder load of the full element tree | 🟡 |
| POST | `/funnels/builder/autosave/<pageId>` | Save (`pageType:"draft"`, `manualSave:true`) or **Publish** (`pageType:"live"`, no `manualSave`) | 🟡 |
| POST | `/funnels/builder/prebuilt-section/sync/changes` | Pre-save sync of saved/prebuilt sections; fires twice per Save (`write:false` then `write:true`) | 🟡 |
| POST | `/funnels/builder/element-template/sync/changes` | Pre-save sync of saved element templates | 🟡 |
| POST | `/funnels/builder/global-sections/<funnelId>` | Writes the funnel's global sections blob; last call of every Save/Publish | 🟡 |
| POST | `/funnels/funnel/delete-step` | Delete a step and its page | 🟡 |
| POST | `/funnels/funnel/update-settings` | Funnel rename and settings (full body) | 🟡 |
| POST | `/funnels/builder/funnel-share-url` | Create a "share funnel" link | 🟡 |
| GET | `/funnels/builder/funnel-share-details/<funnelId>` | Existing share link; 400 `Share funnel not found` when none | 🟡 |
| GET | `/funnels/lookup/list?funnelId=&locationId=&typeId=<stepId>` | Per-step lookup (always `{data:[]}` in captures; likely step redirects) | 🟡 |
| GET | `/funnels/lookup/redirect/regex?domainId=<id>&locationId=<loc>` | Domain redirect rules (304, no body seen) | 🟡 |
| GET | `/funnels/domain/?locationId=<loc>` | Connected domains: `domains[].{id, url, defaultDomain, defaultPage, robotsTxtCode, provider, steps}` | 🟡 |
| GET | `/funnels/builder/redis-key-data/<pageId>` | Builder unsaved-change cache, `{data:null}` normally | 🟡 |
| GET | `/funnels/builder/section-data/<loc>?url=<global-sections download URL>` | Builder proxy-reads the global sections blob | 🟡 |
| GET | `/funnels/custom-fonts?locationId=&limit=100&skip=0` | Uploaded custom fonts, `{data:[]}` | 🟡 |
| GET | `/funnels/builder/section-template?locationId=&limit=20&offset=0` | Saved section templates, `{data:[]}` | 🟡 |
| GET | `/funnels/builder/prebuilt-section?locationId=` | Prebuilt section categories | 🟡 |
| GET | `/funnels/builder/prebuilt-section/hero/template/hero/hero?locationId=` | Prebuilt hero templates | 🟡 |
| GET | `/funnels/order-form/public/products?locationId=&funnel=<id>&step=<stepId>` | Products on an order-form step, `{products:[]}` | 🟡 |
| GET | `/countdown-timer/?locationId=&offset=0&limit=20&status=draft&isExpired=false` | Countdown timers for the timer element, `{countdownTimers:[], total:[]}` | 🟡 |
| GET | `/chat-widget/list?limit=100&offset=0&locationId=` | Chat widgets for the funnel settings picker, `{chatWidgets:[], totalCount}` | 🟡 |
| GET | `/funnel-ai/sessions/pages/<pageId>/active?locationId=` | AI builder session; 404 `No active session found for this page` | ⚠️ |
| GET | `/funnel-ai/copilot/assist-preference/<pageId>?locationId=` | AI assist preference; 404 when unset | ⚠️ |

### Body / response notes

Delete a step (body has no `locationId`):
```json
POST /funnels/funnel/delete-step
{"funnelId": "<funnelId>", "stepId": "<stepUuid>"}
-> {"ok": true}
-> repeat on the same step: 404 {"message": "Funnel Step not found!"}
```

Publish a page (same endpoint and body as Save):
```json
POST /funnels/builder/autosave/<pageId>
{"funnelId": "<funnelId>", "pageVersion": <doc.pageVersion>, "pageType": "live",
 "pageData": {"sections", "settings", "general", "pageStyles", "trackingCode", "fontsForPreview", "popups", "popupsList"},
 "integrations": {"videoBackground": false, "blogMeta": {"selectedBlogCategories": [], "categoryNavigationList": []}, "heading": 2, "image": 1, "customCode": 1, "popup": false}}
-> {"pageDataUrl": "funnel/<fid>/page/<pid>/page-data-<uuid>", "pageDataDownloadUrl": "<firebase url>"}
```
Draft save is identical plus `"manualSave": true` and `"pageType": "draft"`. The autosave body can also carry `"meta": {"title", "description", "author", "keywords", "imageUrl", "language", "canonicalMeta": [], "customMeta": []}`: that is how page SEO meta is set. `integrations` is a count of element types on the page (`heading`, `subHeading`, `image`, `form`, `button`, `customCode`) plus `popup`/`videoBackground` flags.

Sync calls (sent before the autosave, bodies take the same `pageData`):
```json
POST /funnels/builder/prebuilt-section/sync/changes  {"pageData": {...}, "locationId": "<loc>", "pageId": "<pid>", "write": false|true, "isPublished": false|true}
-> {"prebuiltSectionTemplates": []}
POST /funnels/builder/element-template/sync/changes  {"pageData": {...}, "locationId": "<loc>", "pageId": "<pid>", "write": true}
-> {"changedSyncElements": []}
POST /funnels/builder/global-sections/<funnelId>     {"version": <funnel.globalSectionVersion + 1>, "sectionData": []}
-> {"globalSectionsPath": "funnel/<fid>/global-sections-<n>", "globalSectionsDownloadUrl": "<firebase url>"}
```

Share link:
```json
POST /funnels/builder/funnel-share-url  {"funnelId": "<fid>", "shareWith": "ALL", "companyId": "<companyId>"}
-> {"data": {"shareId": "<24-hex>"}}
GET  /funnels/builder/funnel-share-details/<fid>  -> {"data": {"funnelName", "shareWith": "ALL", "shareId"}}
```

### UI action sequences

- **Save (builder Save button)**: `GET /funnels/page/<pid>` and `GET /funnels/funnel/fetch/<fid>` (refresh), `POST prebuilt-section/sync/changes {write:false}`, refresh again, `POST prebuilt-section/sync/changes {write:true}`, `POST element-template/sync/changes`, `POST autosave/<pid> {pageType:"draft", manualSave:true}`, `POST global-sections/<fid>`. Then the UI re-reads page and funnel.
- **Publish**: exactly the same five writes, with `isPublished:true` on the prebuilt sync and `pageType:"live"` (no `manualSave`) on autosave. The page doc then shows a new `versionHistory[0].pageType:"live"`. There is no separate publish endpoint.
- **Delete step/page (funnel overview)**: one `POST /funnels/funnel/delete-step`, then `GET funnel/fetch` shows the step gone. No separate page delete call.
- **Rename funnel**: `GET funnel/fetch`, `GET /funnels/domain/`, `GET /chat-widget/list` (settings modal), `POST /funnels/funnel/update-settings`, `GET funnel/fetch`.
- **Open builder**: `GET /funnels/builder/page/data`, `GET /custom-data/funnels?types=custom-values`, `GET /funnels/page/<pid>`, `GET redis-key-data`, `GET custom-fonts`, brand-board reads, `GET funnel/fetch`, `GET section-data` (global sections), funnel-ai probes (404), `GET /forms/<formId>` for each embedded form, section templates, prebuilt sections, countdown timers.

### Gotchas

- `pageVersion` in the stored page doc does not change on a draft save. The builder sends doc `pageVersion + 1` on draft saves (the same number on repeat saves in one session: 4 twice with the doc at 3) and the doc value itself on publish (doc 2, live sent 2). A script that sends +1 for both works, so the server is lenient.
- `global-sections` `version` should be `funnel.globalSectionVersion + 1`. The builder once sent `1` while the funnel was at 4 and the funnel's version dropped to 1: harmless with empty `sectionData`, but read the funnel first.
- `funnel/fetch/<id>` (UI) and `funnel/<id>?locationId=` (`_data`, snake_case) are two shapes of the same funnel; `fetch` gives camelCase and the global sections fields.
- All funnel reads in the HARs use `version: 2021-07-28` too, not `2021-04-15`.
- `funnel-share-details` 400 just means no share link yet.

---

## forms

Form builder CRUD on the `services.` host, plus version history.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `services./forms/?skip=0&limit=5&locationId=&query=&type=form&productType=form[&parentId=<folderId>]` | List forms (root or one folder) | 🟡 |
| GET | `services./forms/?...&type=folder&productType=form` | List form folders | 🟡 |
| GET | `services./forms/folder/<folderId>` | One folder: `{folder:{_id, name, type:"folder", productType:"form"}}` | 🟡 |
| POST | `services./forms/` | Create blank form | 🟡 |
| GET | `services./forms/<id>` | Full form: `formData` + `versionHistory[]` | 🟡 |
| POST | `services./forms/<id>` | Save (rename, fields, settings). Each save adds a version | 🟡 |
| DELETE | `services./forms/<id>` | Soft delete, returns the doc with `deleted:true` | 🟡 |
| GET | `/forms/<id>` (backend host) | **Metadata only**: no `formData`, no `versionHistory` | 🟡 |
| GET | `/forms/?locationId=&skip=0&limit=50` (backend) | Form list used by the calendar app | 🟡 |
| GET | `/forms/forms-list/?formIds=<id>` (version `2021-04-15`) | Full form docs (with `formData`) by id; used by the workflow builder for form triggers | 🟡 |
| GET | `services./forms/themes?locationId=` | Theme catalogue (`themes[].{_id, name, default, thumbnail}`) | 🟡 |
| GET | `services./forms/theme-style/<themeId>?locationId=` | Theme style: `fieldStyle`, `fieldCSS`, etc. | 🟡 |
| GET | `services./forms/default-colors?locationId=` | Default swatches | 🟡 |
| GET | `/localization/en-US/?module=customField` | UI strings for the field picker | 🟡 |

### Body / response notes

```json
POST services./forms/   {"locationId": "<loc>", "parentId": "<folderId, optional>", "productType": "form", "source": "landing_page"}
-> {"form": {"_id": "<id>", "name": "Form 5", "formData": {}, "version": 5, "parentId": "<folderId>"}}

POST services./forms/<id>   {"name": "<name>", "formData": {"form": {"fields": [...], "formAction": {...}, "style": {...}, "fieldStyle": {...}, "fieldCSS": "...", "currentThemeId": "<themeId>", "stickyContact": false, ...},
                             "emailNotifications": false, "autoResponder": false, "parentFolderId": "", "parentFolderName": "", "language": "en-US",
                             "recurringProductId": null, "recurringProductCurrency": "USD", "recurringProducts": []}}
-> {"data": {..., "formData": {...}, "versionHistory": [{"versionId": "<uuid>", "formDataUrl": "form/<id>/form-data-<uuid>",
                                                         "formDataDownloadUrl": "https://storage.googleapis.com/highlevel-backend.appspot.com/form%2F<id>%2Fform-data-<uuid>",
                                                         "updatedAt", "updatedBy", "updatedByUser"}]}}
```
`version: 5` on the form doc is the builder version, not a history counter. Rename = the same save with a new `name`.

Form version history: `versionHistory[]` is newest first, one entry per Save (6 on an older form, 4 after a short session). Each points at a full JSON snapshot in GCS. Previewing an old version in the UI opens the public widget: `https://<form domain>/widget/form/<formId>?versionId=<versionId>&notrack=true`. A **restore** call was not captured.

### UI action sequences

- **New form**: `POST services./forms/` (blank, "Form N"), then the builder loads: custom fields, `GET /forms/<id>` (backend, metadata), payments/products, brand-board colours, `GET default-colors`, `GET services./forms/<id>` (full), custom field search (fields and folders), objects, pipelines, themes, theme-style.
- **Save**: one `POST services./forms/<id>` with the whole `{name, formData}`, then the builder re-reads custom field search (fields + folders).
- **Delete (list page)**: `DELETE services./forms/<id>`, then the folder list is re-read.

### Gotchas

- Read forms on the `services.` host. The backend `GET /forms/<id>` drops `formData` and `versionHistory`, so a backup taken from it is empty.
- `customFieldLabel` alone is safe: the builder itself adds it to native elements on later saves with no cloning. The clone trigger is `"custom": true` without `customEdited:true` / `__pendingClone:false`. A builder-made custom element ends with `custom:true, customEdited:true, __pendingClone:false` and `fieldKey: contact.contact<key>`.
- `formDataDownloadUrl` has no token. It is probably public (not tested).
- DELETE and save responses come back base64-encoded in HARs; decode before parsing.

---

## surveys

Same service and shapes as forms, with `slides[]`.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `services./surveys/` | Create blank survey ("Survey N") | 🟡 |
| GET | `services./surveys/<id>` | Full survey | 🟡 |
| GET | `/surveys/<id>` (backend) | Survey doc (full in this capture) | 🟡 |
| POST | `services./surveys/<id>` | Save `{name, formData}`, adds a `versionHistory` entry | 🟡 |
| GET | `services./surveys/?skip=0&limit=5&locationId=&query=&type=survey` / `type=folder` | List surveys / folders | 🟡 |
| GET | `services./surveys/themes?locationId=` | Survey themes | 🟡 |
| GET | `services./surveys/theme-style/<themeId>?locationId=` | Survey theme style | 🟡 |

### Body / response notes

```json
POST services./surveys/  {"locationId": "<loc>", "source": "landing_page"}
-> {"survey": {"_id": "<id>", "name": "Survey 0", "version": 4,
               "formData": {"form": {"company": {...}}, "slides": [{"id": "<ms-timestamp>-0", "slideName": "Slide 1", "slideData": [], "button": {...}, "active": false}], "surveyLogicLinkById": true}}}

POST services./surveys/<id>  {"name": "...", "formData": {"fieldCSS", "mobileFieldCSS", "form", "slides": [...], "surveyLogicLinkById": true, "newFooter", "enablePartialContactCreation",
                              "emailNotifications", "autoResponder", "parentFolderId", "parentFolderName", "recurringProductId", "recurringProductCurrency", "recurringProducts", "language"}}
```

### UI action sequence: Quick Add a new field inside the survey builder, then Save

1. `POST services./locations/<loc>/customFields/` `{"name": "Survey | <survey name>", "documentType": "folder", "model": "contact"}` (a custom field folder per survey, created when the first quick-add field is made).
2. On Save: `POST services./locations/<loc>/customFields/` `{"name": "<label>", "fieldKey": "<generated key>", "dataType": "NUMERICAL", "documentType": "field", "showInForms": true, "model": "contact", "parentId": "<folderId>", "description": ""}`.
3. `POST services./surveys/<id>` with the element shaped `{"type": "rating", "dataType": "RATING", "custom": true, "customEdited": true, "__pendingClone": false, "id"/"tag": "<new field id>", "fieldKey": "contact.<key>", "parentId": "<folderId>", ...}`.

### Gotchas

- A Rating element's backing custom field is created as `NUMERICAL`, while the element says `dataType: "RATING"`.
- Quick Add leaves a `Survey | <name>` (or form equivalent) folder in custom fields; snapshot audits will see these.
- Survey slide ids are millisecond timestamps with a suffix (`"1782651485345-0"`), not uuids.

---

## emails (with email-ai, snippets, links, email-isv)

Email builder templates. `ENDPOINTS.md` covers the basics; the captures add the folder and listing reads, the save response, and the origins.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/emails/builder?locationId=&limit=10&sortByDate=desc&archived=false&offset=0&name=&templatesOnly=false[&parentId=]` | Template list (root or folder) | 🟡 |
| GET | `/emails/builder/all?locationId=&type=folder&deleted=false&archived=false&limit=20&offset=0[&id=<folderId>]` | Folder list (flat array) for the Move dialog | 🟡 |
| GET | `/emails/builder/all?locationId=&deleted=false&fields=versionHistory,builderVersion,fromAddress,fromName,subjectLine,previewText,locationId,type,id,archived,emailData,downloadUrl,dateAdded,dateUpdated` | Flat template list with chosen fields (calendar app's template picker) | 🟡 |
| GET | `/emails/builder/folder-path/<loc>/<folderId>` | Breadcrumb `[{id, name}]` | 🟡 |
| POST | `/emails/builder/folder` | Create folder | 🟡 |
| POST | `/emails/builder/clone` | Clone template | 🟡 |
| POST | `/emails/builder/move` | Move into folder | 🟡 |
| DELETE | `/emails/builder/<loc>/<templateId>` | Delete | 🟡 |
| GET | `/emails/builder/meta/<loc>/<tid>?isInternal=false` | Meta | 🟡 |
| PUT | `/emails/builder/meta/<tid>` | Subject, preview, sender | 🟡 |
| GET | `/emails/builder/data/<loc>/<tid>?isInternal=false` | `editorData` (MJML tree) | 🟡 |
| POST | `/emails/builder/data` | Save builder source | 🟡 |
| GET | `/emails/builder/settings/<loc>` | Builder settings: `logoUrl`, `swatches[]`, `customFonts[]`, `verifiedEmails[]`, `unsubscribeType` | 🟡 |
| GET | `/emails/saved-element/<loc>?excludedElements=mj-form;mj-product` | Saved blocks, `{elements:[], totalCount}` | 🟡 |
| GET | `/emails/default-emails/settings/company/<companyId>` | Agency default email settings (304, no body) | 🟡 |
| GET | `/snippets/<loc>?all=true` | Snippets and snippet folders (`isFolder`, `name`, `urlAttachments`) for the merge picker | 🟡 |
| GET | `/links/?locationId=` | Trigger links `{links:[{id, name, redirectTo, fieldKey, isInternal}]}`; email builder adds headers `internal-channel: email-builder` and `location-id: <loc>` | 🟡 |
| GET | `/email-ai/chat/assist-preference/<tid>?locationId=` | AI assist preference (200, no body captured) | 🟡 |
| GET | `/email-ai/chat?locationId=&templateId=` | AI chat history, 404 when none | ⚠️ |
| POST | `/email-isv/set/status` | `{locationId}` -> `{hasLcEmail, emailCharges, domain}`. Fires on every app load; a cheap "is LC Email set up, which sending domain" check for audits | 🟡 |
| GET | `/email-isv/analytics/email/health-report-data?locationId=&startDate=&endDate=` (version `2021-04-15`) | Deliverability health report; 400 `LESS_THAN_500_EMAILS_SENT` under 500 sends | ⚠️ |

### Body / response notes

```json
POST /emails/builder/folder  {"name": "<folder>", "locationId": "<loc>", "type": "folder", "updatedBy": "<userId>"}
POST /emails/builder/clone   {"locationId": "<loc>", "templateId": "<srcTid>", "name": "<new name>", "updatedBy": "<userId>"}
POST /emails/builder/move    {"id": "<tid>", "locationId": "<loc>", "parentId": "<folderId>", "updatedBy": "<userId>"}  -> {"ok": true}
POST /emails/builder/data    {"locationId", "templateId", "updatedBy", "dnd": {"elements", "attrs", "templateSettings"}, "html": "", "editorType": "builder", "previewText": ""}
-> {"ok": true, "id": "<tid>", "versionId": "<24-hex>", "previewUrl": "<firebase index.html>", "templateDataDownloadUrl": "<firebase>"}
PUT  /emails/builder/meta/<tid>  {"fromName": "", "subjectLine": "...", "fromAddress": "", "previewText": "", "locationId": "<loc>", "updatedBy": "<userId>", "fieldDefaults": {}}
-> full meta incl. "name", "builderVersion": "2", "templateSource", "previewUrl"
```
Button element as the builder stores it: `attrs["mj-button-<id>"].attributes` has `redirectAction: "url"`, `url: "<as typed, no scheme added>"`, `href: ""`, and the label in `content`.

### UI action sequences

- **Templates page, new folder + clone + edit + move + delete**: `POST folder`, `GET builder` list, `POST clone`, list again; builder opens: `GET /custom-data/emails?types=custom-values`, `GET meta`, `GET settings`, brand-board reads, `GET /businesses/`, `GET saved-element`, `GET data`, `GET snippets`, `GET /custom-fields/object-key/business`, `GET links`, Firebase `index.html`, `GET email-ai/*`; Save = one `POST data` (then Firebase preview re-fetch with `lastSavedOn`); Move dialog = `GET builder/all?type=folder` twice, `POST move`, `GET folder-path`; Delete = `DELETE /emails/builder/<loc>/<tid>`, list again.
- **Edit button, then subject**: `POST data` on Save, later a separate `PUT meta` when the subject is changed. Subject is never in the data save.

### Gotchas

- Origins differ per call (see table at top). In captures `POST /emails/builder/data` comes from `email-builder-prod` and the meta PUT from the whitelabel app origin, yet the same writes sent with the `email-home-prod` origin also work, so the server does not seem to check; mirror the capture if a call is refused.
- `/emails/builder` lists one folder level only; `/emails/builder/all` returns a flat array (folders only when `type=folder`).
- The data save returns a `versionId`: email templates keep version history too (`versionHistory[]` with `downloadPath` / `downloadUrl` in `builder/all`).

---

## brand-boards

Brand kit (colours, fonts, voice) read by the page, form and email builders. Only reads were captured, and most bodies were not saved.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/brand-boards/<loc>?limit=10&offset=0` | List brand boards (no body captured) | 🟡 |
| GET | `/brand-boards/<loc>/default` | The default board; 404 code 6001 `Brand board not found` when none is set | ⚠️ |
| GET | `/brand-boards/custom-colors/<loc>/all` (backend or `services.`) | Saved colours `{customColors:[], total}` | 🟡 |
| GET | `/brand-boards/custom-fonts/<loc>?limit=100&offset=0` | Brand fonts (no body captured) | 🟡 |
| GET | `/brand-boards/voices/<loc>?limit=10&offset=0` | Brand voice entries (no body captured) | 🟡 |

### Gotchas

- The 404 on `/default` is the normal state for an account with no brand board; it is not an auth problem.
- The form and survey builders call these on the `services.` host, the page and email builders on backend.
- No create or update call is captured. A HAR of Settings > Brand Boards is needed before scripting brand kits.

---

## membership and clientclub

Courses, offers and the client portal. Read-only so far.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/membership/smart-list/offers-products/<loc>` (version `2021-07-28`) | **Lists membership products and offers** by name and id | 🟡 |
| GET | `/membership/locations/<loc>/settings/site-info/` (version `2021-04-15`) | Membership site settings: `title, supportEmail, supportPhone, logoUrl, faviconUrl, headerScript, customJs, customCss, loginCode, customHeader, customFooter, pageTitle, pageDescription, seoImage, clientPortal (bool), generalSettings` | 🟡 |
| GET | `/membership/locations/<loc>/settings/builder-settings` (version `2021-04-15`) | Builder settings (no body captured) | 🟡 |
| GET | `/clientclub/portal-settings/<loc>` | Client portal config | 🟡 |

### Body / response notes

```json
GET /membership/smart-list/offers-products/<loc>
-> {"products": [{"product_name": "<course name>", "product_id": "<uuid>"}],
    "offers":   [{"offer_name": "<offer name>", "offer_id": "<uuid>", "source": "membership"}]}
```
Seen with 6 products and 2 offers on one location, empty arrays elsewhere. The UI calls it on app load (smart-list filters), with origin = whitelabel app.

### Gotchas

- Offers and products are often said to be unreachable with the internal token. This endpoint returns their names and ids (not course content or pricing); one read-only GET with the internal token confirmed it.
- `site-info` and `builder-settings` need `version: 2021-04-15`; the offers-products and clientclub calls use `2021-07-28`.

---

## Noise

- `GET services./funnels/funnel/geo-location/` and backend `geo-location` (version `2021-04-15`, on public forms): visitor country lookup.
- `POST /forms/form-survey-event` (version `2021-04-15`, origin `lclink.co`, header `x-parent-trace-context`): public form view and load-time telemetry `{fingerprint, eventType: "form-view"|"form-load-time", mediumId, medium: "form", locationId, name, ...timings}`. Status 0 rows are cancelled beacons.
- `GET services./chat-widget/public/config/<widgetId>` (header `widget-id`, `source: custom-code`): the agency support chat widget config on app load.
- `GET /localization/en-US/?module=customField`: UI translation strings.
- `GET /lists/dynamic/<loc>?objectKey=calendar&limit=30` (version `2021-04-15`): smart lists for the calendar module, `{smartlists:[], total}`.
- `GET auth.locationapi.co/resources1?d=<whitelabel domain>&v=<ts>`: whitelabel resource check, `{mce, ce}`.
- `GET /funnels/builder/redis-key-data/<pageId>`, `GET /funnel-ai/*`, `GET /email-ai/*`, `POST /email-isv/set/status`: builder and app-load probes (the last is useful for audits, see emails).
- `data.pathfinder.gohighlevel.com/data/rec/*`, `featureassets.org`, `prodregistryv2.org`, `unleash-proxy.mycrmsupport.net`, `commsmessenger.com`: session recording, feature flags and support widgets.

---

# 4. Reporting and dashboards

A few rows are 304 only, marked "304": the browser had it cached, the HAR still holds the body.

Headers for every `backend.leadconnectorhq.com/reporting/dashboards/*`, `/reporting/custom-metrics*` and `/reporting/opportunities/*` call: `token-id`, `channel: APP`, `source: WEB_USER`, `version: 2021-04-15`, `x-reporting-api-version: 3`, `content-type: application/json` on writes. `locationId` goes in the query string (`?locationId=<loc>`) for every dashboards query, except `widget-preference`, `preference` and `sales-velocity`, which carry it in the body only.
`/reporting/notification/*` uses a different set: `version: 2021-07-28` (not 2021-04-15), no `x-reporting-api-version`, and query `locationId, userId, companyId`.
`/reporting/external-google-analytics/*` was sent without `x-reporting-api-version`.

---

## Dashboard query engine (`POST /reporting/dashboards/<module>`)

This is how every "new style" widget gets its numbers. You can call it directly with the same body to pull a dashboard number without the UI. The endpoint for each module comes from `widgets-definitions` (`data.definitions.*._settings.apiConfig.path`), and each stored widget repeats it as `widget.apiConfig.path`.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `/reporting/dashboards/crm/contacts?locationId=<loc>` | Contact count/table/breakdown | 🟡 |
| POST | `/reporting/dashboards/crm/opportunities?locationId=<loc>` | Opportunity count, sum/min/max/avg of `monetary_value`, breakdowns | 🟡 |
| POST | `/reporting/dashboards/crm/emails?locationId=<loc>` | Email event counts (delivered, clicked, replied...) by source or by day | 🟡 |
| POST | `/reporting/dashboards/revex/calls?locationId=<loc>` | Call counts (direction, status, user) | 🟡 |
| POST | `/reporting/dashboards/leadgen/funnel-stats?locationId=<loc>` | Funnel/website page views (unique or all) | 🟡 |
| POST | `/reporting/custom-metrics/dashboard?locationId=<loc>` | Evaluate a saved custom metric (already documented) | 🟡 |

Paths in the catalogue but never called in a HAR (same body shape, untested): `/dashboards/crm/sms`, `/dashboards/crm/conversations`, `/dashboards/crm/conversations-sla`, `/dashboards/automations/appointments` (+ `/automation-appointments-services`, `/automation-appointments-rentals`), `/dashboards/leadgen/payments/leadgen-payments-{transactions,subscriptions,orders,invoices,refunds}`, `/dashboards/automation/admanager/{fb-ads,google-ads}`, `/dashboards/leadgen/social-planner`, `/dashboards/external/google-analytics`. All sit under `/reporting`.

### Body / response notes

One body shape for all modules:

```json
{
  "chartType": "numeric",
  "options": {
    "aggregations": [{"operator": "count", "field": "id", "i18nKey": "common.widget.metricCountOfOpportunity",
                      "fieldLabel": "Opportunity", "numberFormatType": "none", "metricKey": "count::id"}],
    "filters": [{"group": "AND", "filters": [
      {"field": "date_added", "operator": "time_series", "value": [<startMs>, <endMs>]},
      {"group": "OR", "filters": [
        {"group": "AND", "filters": [
          {"field": "pipeline_id", "operator": "eq", "value": "<pipelineId>"},
          {"field": "status", "operator": "eq", "value": "won"}
        ]}
      ]}
    ]}],
    "comparisonPositiveIndicator": true,
    "timezone": "Europe/London"
  },
  "externalDataConfig": null
}
```

- The query body is not the same as the stored widget's `options`. The UI wraps the widget's stored `filters` (an OR group) inside an outer `AND` group whose first leg is `{field: <widget.options.dateProperty>, operator: "time_series", value: [startMs, endMs]}`. It resolves `dateRangeOverride` (or the dashboard date range) to epoch ms at local midnight in `timezone`, and adds `i18nKey`, `fieldLabel` and `metricKey` to each aggregation. An empty OR (`{"group":"OR","filters":[]}`) means no extra filters.
- `metricKey` = `<operator>::<field>` (e.g. `count::id`, `sum::monetary_value`, `count::_id` for calls, `count::page_view` for funnel stats).
- Date field per module: contacts/opps `date_added` (also `date_updated`, opps `last_status_change_date`, contacts `date_of_birth`, `last_activity`), emails/sms `createdAt`, calls `dateAdded`, funnel stats `createdAt`, conversations `last_message_date`.
- Comparison: add `options.comparisonDate: {"field": "createdAt", "operator": "time_series", "value": [<prevStartMs>, <prevEndMs>]}`. The response then also carries `comparisonData` and `stats {total, comparisonTotal, percentageChange}`. Without it you get only `data`.
- Breakdown / chart variants:
  - `numeric`: no `groupBy`. Response `data[0].data = {"label": "total", "value": 46}` (calls give `label: null` plus `total`; custom metric gives `value: "12%"` as a string).
  - `line` / `bar` over time: `groupBy: {"fields": [{"field": "date_added", "type": "time_series", "interval": "monthly"}], "limit": null, "orderBy": "asc"}`. Intervals: daily, weekly, monthly, quarterly, yearly. Response `data[0].data = [{"id": <bucketStartMs>, "label": "Sep 26", "value": 45}, ...]`, `total`.
  - `bar` / `donut` / `horizontal_bar` by field: `groupBy: {"fields": [{"field": "source", "type": "field"}], "limit": 10, "orderBy": "desc"}`. Response `data = [{"label": "Workflow", "value": 7310, "id": "workflow"}, ...]`. The group field must be the exact `value` from `widgets-definitions.groups.<module>.fields` including its suffix: `tags.raw`, `source.raw`, `custom_fields.<id>.raw` (contacts) or `custom_fields.<id>.keyword` / `.raw` (opps), `attributions.medium.keyword`.
  - `table` (contacts seen): `options.tableProperties: {"order": "desc", "orderBy": "contactName", "limit": 10, "page": 1, "columns": [...]}`. Column keys: `contactName, email, phone, company, source, tags, dateAdded, assignedTo, utmSource, utmCampaign, utmMedium, ...`, custom fields as `customFields.<id>`. Response `data[0] = {metricKey, data: [rows], total, columns}`. This is a paged contact list with attribution, filtered like any widget.
- Filter values seen: opps `pipeline_id`, `pipeline_stage_id`, `status` (open/won/lost/abandoned), `name contains`, `custom_fields.<oppFieldId> eq`; contacts `tags eq "<tag>"`, `custom_fields.<contactFieldId> eq`; emails `status` = `events_accepted|events_delivered|events_opened|events_clicked|events_replied|events_temporary_fail|events_permanent_fail|events_failed|events_unsubscribed`, `source` = `workflow|email_marketing_campaign|campaign|bulk_request|template|other`, plus `workflowId`, `templateId`, `bulkRequestId`, `meta_sendingDomainName`; calls `direction` inbound/outbound, `callStatus` completed/busy/no-answer/canceled/failed/voicemail, `firstTime`; funnel stats `pageType` funnel/website, `aggregationType` unique/all, `funnelId` / `funnelWebsiteId`. The full list of fields and operators per module is `widgets-definitions.data.filters.<module>`.
- `uiMeta` on a filter is ignored by the query engine (queries with and without it both return 201). It only matters for the stored widget: without it the dashboard editor shows blank filter rows.

Recipe, "emails delivered last month by source": POST `/reporting/dashboards/crm/emails`, `chartType: "donut"`, count `id`, group by `source`, filters `[createdAt time_series [start,end]] AND OR[AND[status eq events_delivered]]`. Response splits Email Marketing Campaign / Workflow / Other.

### Gotchas
- `timezone` is the browser's zone, not the account's. Send the account's zone (e.g. `Europe/London`) and ms bounds at that zone's midnight, or day buckets shift by the offset.
- Opportunity queries accepted `custom_fields.<id>` where `<id>` is an OPPORTUNITY custom field ("Service Type", listed in the opp groups catalogue): 201, but the value was 0 so it is not proven to filter. This does not contradict the known limit "cannot filter on CONTACT custom fields", but narrows it: opp-model fields are at least accepted.
- **Bar-chart `groupBy` type.** Some notes say bar-chart bodies need `groupBy.fields:[{field, type:"text"}]`. Every UI field breakdown in the HARs sends `type: "field"` (`"text"` is the type the catalogue lists). Time breakdowns send `type: "time_series"` + `interval`. If `"text"` worked in testing, both are accepted; copy the UI's `"field"` to be safe.
- Custom metric evaluate: the UI body is `{"timezone", "filterDate": [startMs, endMs], "metric": "<id>", "chartType": "numeric"}` with `locationId` in the query only. Older notes put `locationId` in the body and omit `chartType`; both work.
- Funnel-stats `leadgen-funnel-stats` widget uses `comparisonDateProperty: "previous_x_days"`. Comparison presets per module live in `widgets-definitions.comparisonDateProperty` (`dashboard_comparison_date_range`, `no_comparison`, `previous_x_days`, `year_before`, `last_month`...).

---

## Classic (default) dashboard widgets: `/reporting/dashboards/custom*`, sales velocity

The default "Dashboard" that ships with every sub-account uses `module: "custom"` widgets with no `options` and no `apiConfig`. Each identifier calls a fixed endpoint with a flat body. These are the quickest way to get pipeline totals, win rate and lead-source tables.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `/reporting/dashboards/custom?locationId=<loc>` | `chartType` switch: `opportunity_status`, `opportunity_value`, `conversion_rate` | 🟡 |
| POST | `/reporting/dashboards/custom/lead-source?locationId=<loc>` | Opps per contact source with open/won/lost/abandoned and win % | 🟡 |
| POST | `/reporting/dashboards/custom/funnel?locationId=<loc>` | Stage funnel for one pipeline (count, value, cumulative and next-step rates) | 🟡 |
| POST | `/reporting/dashboards/custom/funnel/stage-distribution?locationId=<loc>` | Per-stage counts + Won + Lost/Abandoned, with comparison period | 🟡 |
| POST | `/reporting/opportunities/sales-velocity` | Total sale value, average sale cycle, monthly sale value, vs previous period | 🟡 |

Widget identifier to call: `crm-opportunities-status` = custom `opportunity_status`; `crm-opportunities-value` = `opportunity_value`; `crm-opportunities-conversion-rate` = `conversion_rate`; `automations-attribution-lead-sources` = `custom/lead-source`; `crm-opportunities-funnel` = `custom/funnel`; `crm-opportunities-stages-distribution` = `custom/funnel/stage-distribution`; `crm-opportunities-sales-efficiency` = `opportunities/sales-velocity`; `automations-reporting-google-ads-report` / `-facebook-ads-report` = `ads-manager/*`; `automations-reporting-gmb-report` = `internal-ref/gmb-linked-pages` + `gmb-metrics`; `crm-locations-tasks` = `POST /locations/<loc>/tasks/search`; `crm-conversations-manual-actions` = `POST /conversations/manual-actions`; `email-health-report` = `GET /email-isv/analytics/email/health-report-data`; GA widgets = `GET /appengine/google/get_views` (last four are other domains).

### Body / response notes

```json
POST /reporting/dashboards/custom
{"chartType": "opportunity_status", "startDate": <ms>, "endDate": <ms>,
 "assignedTo": "", "dateProperty": "last_status_change_date", "pipeline_id": ""}
-> {"data": {"total": 86, "totalValue": 0, "counts": [{"label": "Won", "value": 42}, {"label": "Open", "value": 30},
             {"label": "Abandoned", "value": 10}, {"label": "Lost", "value": 4}]}, "stats": {"total": 86, "totalValue": 0}}
```
- `opportunity_value`: same shape, `counts[].value` is money per status.
- `conversion_rate`: `data = {total, totalValue, won, wonValue, conversionRate: "48.84%"}`.

```json
POST /reporting/dashboards/custom/lead-source
{"startDate": <ms>, "endDate": <ms>, "assigned_to": "", "dateProperty": "last_status_change_date",
 "pipeline_id": "", "comparisonStartDate": <ms>, "comparisonEndDate": <ms>}
-> {"data": [{"source": "<contact source or ->", "totalLeads": 44, "totalValues": 0, "open": 20, "lost": 3,
              "won": 14, "abandoned": 7, "winPercentage": "31.82%"}],
    "comparisonData": {"total": 43}, "stats": {"total": 86, "comparisonTotal": 43, "percentageChange": 100}}
```
- `source: "-"` = opps whose contact has no source. Comparison fields are optional (without them, no `comparisonData`).

```json
POST /reporting/dashboards/custom/funnel   (and /funnel/stage-distribution, same body)
{"startDate": <ms>, "endDate": <ms>, "pipeline_id": "<pipelineId>", "assigned_to": "", "dateProperty": "last_status_change_date"}
funnel -> {"data": [{"name": "<stage>", "pipelineStageId": "<id>", "count": 0, "value": 0, "cumulativeRate": "0.00%",
                     "nextStepRate": "100.00%", "position": 0}, {"name": "Won", ...}],
           "stats": {"totalWonCount", "totalWonRevenue", "comparisonTotalWonCount", "comparisonTotalWonRevenue", "percentageChange"}}
stage-distribution -> {"data": {"data": [{"name", "position", "showInPieChart", "revenue", "totalCount", "pipelineStageId",
                       "cumulativeRate"}, {"name": "Won"}, {"name": "Lost/Abandoned"}], "total"},
                       "comparisonData": {same}, "stats": {"total", "comparisonTotal", "percentageChange"}}
```

```json
POST /reporting/opportunities/sales-velocity
{"locationId": "<loc>", "afterDate": {"start": <ms>, "end": <ms>}, "beforeDate": {"start": <prevMs>, "end": <prevMs>},
 "userId": ["noAgents"], "pipeline_id": "", "dateProperty": "last_status_change_date"}
-> {"result": {"totalSaleValue", "totalSaleValueOld", "totalSaleValuePercentage", "averageSaleCycle", "averageSaleCycleOld",
               "averageSaleCyclePercentage", "monthlySaleValue", "monthlySaleValueOld", "monthlySaleValuePercentage"}}
```

### Gotchas
- Key spelling differs: `/custom` takes `assignedTo`, the other three take `assigned_to`. `pipeline_id: ""` = all pipelines (status, value, conversion, lead-source); funnel and stage-distribution need a real pipeline id.
- No `timezone` in these bodies: send absolute epoch ms (the UI sent local-midnight bounds, e.g. 23:00Z for BST).
- `dateProperty` comes from the dashboard preference `oppDateProperty` (`last_status_change_date` in every HAR). With that, "total 86" means opps whose status changed in the window, not opps created in it. Send `date_added` for a created-in-period cohort.
- Empty periods return `cumulativeRate: "NaN%"`.
- `userId: ["noAgents"]` is what the UI sends for "all users" on sales velocity.

---

## Dashboard shell: load-time reads and per-user prefs

What the UI fetches when a dashboard opens, plus the small preference writes it fires on its own.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/reporting/dashboards/{id}/user/quick-filters?locationId=<loc>` | Saved quick filters for this user on this dashboard | 🟡 |
| GET | `/reporting/dashboards/{id}/permissions?locationId=<loc>` | Sharing per role, private flag, owner | 🟡 |
| GET | `/reporting/dashboards/{id}/sticky-notes?locationId=<loc>` | Dashboard sticky notes (empty in HAR) | 🟡 |
| PUT | `/reporting/dashboards/{id}/widget-preference` | Save a classic widget's own filter choice | 🟡 |
| PUT | `/reporting/dashboards/{id}/preference` | Save dashboard date range / `oppDateProperty` (documented) | 🟡 |
| GET | `/reporting/dashboards/{id}/widgets?locationId=<loc>` | Layout records + widget stubs (documented as stubs) | 🟡 |

### Body / response notes
```json
GET permissions -> {"data": {"permission": [{"role": "agency_user", "permission": "full"},
                                           {"role": "account_user", "permission": "read"}],
                             "isPrivate": false,
                             "dashboardOwner": {"id": "<userId>", "name": "<name>", "email": "<email>", "type": "agency", "role": "admin"}}}
```
Roles seen: `agency_user`, `account_admin`, `account_user`. Permissions seen: `full`, `read`. Useful for an audit: "can client users edit this dashboard?".

```json
GET quick-filters -> {"data": {"locationId": "<loc>", "dashboardId": "<id>", "quickFilters": []}}
GET sticky-notes  -> {"success": true, "message": "Sticky notes fetched successfully", "data": []}

PUT widget-preference  {"locationId": "<loc>", "widgetId": "<widgetId>", "options": {"filters": {...}}}
-> {"success": true, "message": "Widget preference updated successfully", "data": null}
```
`options.filters` variants seen: tasks widget `{"filterBy": "pending", "orderBy": "dueDate,asc", "assignedTo": "all"}`; opportunity widgets `{"userId": "all", "pipeline_id": "all"}`; manual actions `{"campaign": "all", "assignee": "all", "automationType": "workflow", "selectedOption": {"label": "All", "value": "all"}}`; GMB widget `{"pageId": "<Google placeId>"}`. Saved values come back in `GET /reporting/dashboards/{id}` as `data.widgetPreferences[]`.

### Gotchas
- Simply opening the default dashboard WRITES: the UI PUTs `/preference` (`oppDateProperty`) and one `widget-preference` per classic widget on load, twice for some. Harmless, but a HAR of "just looking" will contain PUTs.
- Load order seen: `GET /reporting/dashboards` (list + `defaultDashboardId`) then in parallel `GET /{id}`, `/user/quick-filters`, `/permissions`, `/widgets-definitions`, then the widget queries.
- Sticky notes write endpoints were not captured (only the empty GET). Not the same API as workflow sticky notes (`/workflows/sticky-notes-all`).

---

## Internal-ref lookups (`/reporting/dashboards/internal-ref/*`)

Id to label lists the widget editor uses to fill filter dropdowns. They are handy, cheap lookups for building filters. They return a bare JSON array (no `data` envelope).

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/reporting/dashboards/internal-ref/pipelines?locationId=<loc>` | `[{"label": "<pipeline>", "value": "<pipelineId>"}]` | 🟡 304 |
| GET | `/reporting/dashboards/internal-ref/stages?locationId=<loc>&pipelineId=<id>` | `[{"label": "<stage>", "value": "<stageId>"}]` in pipeline order | 🟡 304 |
| GET | `/reporting/dashboards/internal-ref/customFields?locationId=<loc>` | Contact custom fields: `[{"label", "value": "<fieldId>", "type": "TEXT", "keyValuePair": null or [{label, value}]}]` | 🟡 304 |
| GET | `/reporting/dashboards/internal-ref/gmb-linked-pages?locationId=<loc>` | Google Business Profile pages linked to the location | 🟡 |
| GET | `/reporting/dashboards/internal-ref/gmb-metrics?locationId=<loc>&pageId=<placeId>` | GBP metrics for one page (body not captured) | 🟡 |

Other refs named in `widgets-definitions` but not called: `users`, `tags`, `calendars`, `calendar-groups`, `funnels`, `websites`, `contacts`, `lost-reasons` (documented), `customFields?model=opportunity`, `businesses`, `leads`, `domains`, `sub-source?source=workflow|campaign|template|email_marketing_campaign|bulk_request&actionType=bulk-email|bulk-sms`, `fb-ad-accounts`, `fb-ad-entities?entityType=campaign|adset|ad`, `google-ad-entities?entityType=campaign|ad-group|ad`, `social-accounts`.

### Body / response notes
```json
GET gmb-linked-pages
-> {"linkedPages": [{"id", "pageName", "displayName", "placeId", "altId": "accounts/<n>/locations/<n>",
                     "messagingStatus": "Success", "locations": {"<loc>": true}, "welcomeMessage", "agentName", ...}],
    "messaging": {"names": [], "errors": []},
    "callTracking": {"status": "Disabled", "error": "", "pageName": "", "placeId": "", "altId": ""},
    "connectionErrors": [], "success": true, "ownerId": "<id or null>"}
```
Audit use: empty `linkedPages` = no GBP connected; `messagingStatus`, `callTracking.status` and `connectionErrors` show GBP chat and call-tracking health.

### Gotchas
- `customFields` with no `model` returned only contact-model fields (104 in one capture). For select fields `keyValuePair` holds the option list, which is what a filter `value` must match.
- `sub-source?source=workflow` is the likely way to list workflows/campaigns for the email/SMS `workflowId` / `campaignId` filters (untested).

---

## Ads manager and Google Analytics connections

The classic ad widgets and the GA data-source picker. The ad endpoints only errored in the HARs, but the error text is a good connection check for an audit.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/reporting/ads-manager/google-ads?locationId=<loc>&startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&fields=clicks,cost_micros,average_cpc,ctr&type=INTEGRATION` | Google Ads totals for the period | ⚠️ |
| GET | `/reporting/ads-manager/facebook-ads?locationId=<loc>&startDate=&endDate=&fields=clicks,spend,cpc,ctr&type=INTEGRATION` | Facebook Ads totals | ⚠️ |
| GET | `/reporting/external-google-analytics/accounts?locationId=<loc>` | Google logins connected for GA: `{"data": {"accounts": [{"label": "<email>", "value": "<email>"}]}}` | 🟡 |
| GET | `/reporting/external-google-analytics/ga-accounts?locationId=<loc>&emailId=<email>` | GA accounts: `[{"label": "<name>", "value": "accounts/<n>"}]` | 🟡 304 |
| GET | `/reporting/external-google-analytics/ga-accounts/{n}/properties?locationId=<loc>&emailId=<email>` | GA4 properties: `[{"label": "<name>", "value": "properties/<n>"}]` | 🟡 304 |
| GET | `/reporting/external-google-analytics/ga-properties/{n}/custom-metrics?locationId=<loc>&emailId=<email>` | GA4 custom metrics for a property (`{"data": []}`) | 🟡 |

### Body / response notes (error texts, audit-useful)
- Google Ads 400 `"No Google ads account connected, Please connect a google ads account"` or `"Cannot find google adwords id! Please make sure a google adwords account is connected to the location"` = never connected.
- Google Ads 422 `{"message": "Google Ads integration is broken, please reconnect.", "errorType": "no_integration_error"}` = was connected, token now broken.
- Facebook Ads 400 `"Ad Account not found for location <loc>"` = no ad account picked; `"Access Token not found or it could not be fetched"` = FB integration missing or expired.

### Gotchas
- Ads endpoints take plain `YYYY-MM-DD` dates in the query, not epoch ms.
- GA calls take the Google login email as `emailId`. Chain: accounts, then ga-accounts, then properties, then custom-metrics.
- `ga-accounts/{n}` is the bare number (strip `accounts/`); the same goes for `ga-properties/{n}`.

---

## Notification checks useful for an account audit (`/reporting/notification/*`)

The top-bar banners. Each check is a cheap GET that answers "is X broken on this account?" with `{"show": true|false, "title": ...}`. The full registry, with each check's URL, is one call.

| Method | Path | What it does | Status |
|---|---|---|---|
| GET | `/reporting/notification?companyId=<co>&locationId=<loc>&notificationStatus=not_viewed` | Registry of every banner: alias, title, `externalAPIConfig.endpoint` + `query`, conditions, frequency | 🟡 |
| GET | `/reporting/notification/automation/workflows/unpublished` | "Some of your Workflows were unpublished due to errors in them." Button goes to Workflows filtered `paused` | 🟡 |
| GET | `/reporting/notification/automation/calendar/integration-status-v2` | Calendar / video-conferencing integrations disconnected | 🟡 |
| GET | `/reporting/notification/automation/calendar/connections-with-deleted-calendars` | A connected calendar was deleted on the Google/Outlook side | 🟡 |
| GET | `/reporting/notification/crm/integration/google-integration-status` | Primary Google login expired (GBP, GA...) | 🟡 |
| GET | `/reporting/notification/crm/integration/fb-integration-status` | Facebook integration expired | 🟡 |
| GET | `/reporting/notification/leadgen/social-planner/integration-status?platform=<p>[&type=page\|profile]` | Social Planner account expired, per platform | 🟡 |
| GET | `/reporting/notification/leadgen/marketplace/external-auth-disconnected` | Marketplace app external auth disconnected | 🟡 |
| GET | `/reporting/notification/revex/email-isv/email-blocked-status` | Email sending blocked on this account | 🟡 |
| GET | `/reporting/notification/revex/email-isv/sms-blocked-status` | SMS sending blocked | 🟡 |
| GET | `/reporting/notification/revex/email-isv/smtp-service` · `/mailgun-integration-status-account` | Location SMTP / Mailgun integration problem | 🟡 |
| GET | `/reporting/notification/revex/lc-phone/incoming-call-status` | Inbound calls disabled for suspected spam | 🟡 |
| GET | `/reporting/notification/revex/lc-phone/daily-message-reached` | Daily message limit reached | 🟡 |
| GET | `/reporting/notification/revex/lc-phone/billing-issue-twilio-account` | "Phone number isn't setup. Your calls and SMS may not work" | 🟡 |
| GET | `/reporting/notification/revex/saas/wallet-balance-status-account` · `/low-wallet-balance-account` | Wallet below 0 (SMS/calls/emails start failing) or low | 🟡 |

All take `?locationId=<loc>&userId=<userId>&companyId=<co>`, headers `version: 2021-07-28`, `channel`, `source`, `token-id`.

### Body / response notes
```json
healthy:  {"show": false}
problem:  {"show": true, "title": "Your primary Google account <email> has expired, affecting GBP, Google Analytics, etc."}
problem:  {"show": true, "title": "The connection for the following Social Planner Instagram account(s) has expired: <handle>.",
           "primaryButton": {"action": {"type": "social-planner-reintegration", "data": {"locationId": "<loc>", "platform": "instagram"}}, "text": "Re-integrate"}}
```
Registry entry (one of ~50):
```json
{"alias": "automation-workflows-unpublished", "title": "Some of your Workflows were unpublished due to errors in them.",
 "externalAPIConfig": {"serviceName": "automation-reporting-api", "endpoint": "/automation/workflows/unpublished", "method": "GET"},
 "primaryButton": {"redirect": {"name": "workflows-v2", "query": {"filter": "paused"}}, "text": "Check now"},
 "conditions": {"all": [{"fact": "user", "path": "$.role", "operator": "equal", "value": "admin"}]},
 "frequency": {"unit": "always"}, "type": ["drawer"], "visibility": [{"type": "account"}]}
```
Check URL = `/reporting/notification` + `externalAPIConfig.endpoint`, plus `externalAPIConfig.query` if present (social planner `platform`/`type`, WhatsApp `bannerType`).

### Gotchas
- `show:false` can still carry a `title` (calendar integration-status-v2 always returns the title). Read `show`, not the title.
- The registry lists checks the HARs never called: `/revex/saas/billing-status-account` (payment method missing) and `/payments/integration/stripe-integration-status` (Stripe Connect revoked). Worth adding to an audit (untested).
- "Sub-account paused" has no endpoint. It is evaluated client-side from `location.suspended_info.paused`.
- Agency-scoped checks (`revex/reselling/subscription/pending-payment`, `crm/ai/summer-of-ai`) can 401 "You are not authorized to access this company!" for a location-level token. Treat 401 as "not applicable", not broken.
- The only `show:true` responses captured: Google integration expired, Instagram Social Planner expired. `workflows/unpublished` was always `show:false`, so its `show:true` shape is unconfirmed. It likely just says "some exist" with no list; get the actual workflows from the workflow list `paused` filter.
- The OPTIONS preflights return 204 with no body. Ignore them when parsing a HAR.

---

## Tracking beacons: `attribution_service`, `stats`, `alertpopups`, `scoring`

Not GHL admin APIs. These are the public tracking calls fired by funnel/preview pages and by the agency's own chat widget embedded in the white-label app. They are noise for builds. `scoring/profile` is the only admin call.

| Method | Path | What it does | Status |
|---|---|---|---|
| POST | `backend.leadconnectorhq.com` or `services.msgsndr.com` `/attribution_service/user_session_v3/create_session` | Starts a visitor session (source, referrer, UTM, fbp/fbc, funnel/page ids). Returns `{sessionId, fingerprint}` | 🟡 |
| POST | `services.msgsndr.com/attribution_service/user_session_v3/update_session/{sessionId}` | Adds page visits to a session. Returns `{"msg": "successfully updated the session", fingerprint}` | 🟡 |
| POST | `backend.leadconnectorhq.com/stats/event` | Funnel page view counter: `{eventType: "page_view", funnelId, stepId, pageId, pageType: "funnel", fingerprint, fullUrl, ...}`. Returns 201 `{ok: true}` | 🟡 |
| GET | `customizerapi.locationapi.co/alertpopups` | Third-party white-label customizer (agency's support widget) popups: `{"alertpopups": [], "status": "success"}` | 🟡 |
| GET | `backend.leadconnectorhq.com/scoring/profile?locationId=<loc>` | Lead-scoring profile, loaded by the workflow editor (route editWorkflow) | 🟡 304 |

### Gotchas
- Attribution and stats calls carry no auth header. They are what a published funnel page sends, and they are how a page view and first/last-touch attribution get recorded. Do not replay them: you would inject fake visits into real reporting.
- `stats/event` uses `version: 2021-04-15`. `scoring/profile` uses `version: 2021-07-28` + `token-id`. Its body was not captured (304 with no cached body).

---

## Noise

Banner checks with no audit value (all `GET /reporting/notification/...`, all returned `{"show": false}`):
- Billing / SaaS: `revex/reselling/subscription/pending-payment`, `revex/saas/billing-status-agency`, `revex/saas/billing-status-agency-failed-payment`, `revex/blade-platform/wallet/tax/subaccount-stripe-address-missing`, `payments/tax/taxjar-deprecation-notification`, `revex/internal-tools/tax-id-status`
- Compliance: `revex/internal-tools/hipaa-compliance-status`, `hipaa-baa-resign`, `hipaa-outreach`
- Agency email: `revex/email-isv/mailgun-integration-status-agency`, `revex/email-isv/company-smtp-service`
- Promos: `revex/whatsapp/whatsapp-banners?bannerType=...`, `revex/yext/setup`, `revex/wordpress/hosting-offer`, `revex/desktop-app/{app-ready-banner,enable-promotion-banner,setup-banner,promote-banner}`, `mobile/backend/highsupply-app-update-{available,failed}-status`, `ai/soai/500k-billing-warning`, `crm/ai/summer-of-ai` (401)
- All OPTIONS 204 preflights on `/reporting/*`.

---

# 5. Test sub-account sweep

One capture per feature on a throwaway test sub-account, driving the UI with DevTools recording. Every test item was named `ZZ HAR Test ...` and deleted again in the same capture. Nothing outbound was sent (checked: no send, broadcast, SMS, review-request or invite calls). Areas browsed: dashboard and conversations, calendars, contacts and companies, opportunities and pipelines, payments and products, marketing, automation, every settings page, reputation, funnels and sites, memberships, media, reporting, mobile app and launchpad. Run `har_index.py` over your own sweep for the full endpoint list.

## Write recipes proven in this sweep

All on `backend.leadconnectorhq.com` with `version: 2021-07-28` unless noted (workflow calls send no `version` header).

| Action | Call | Body / notes |
|---|---|---|
| Note on a contact | `POST /notes/?locationId=` | `{body:"<p>html</p>", title, color:"#fef7c3", relations:[{objectKey:"contact", recordId}]}` → `{note:{id}}`. Delete: `DELETE /notes/{id}?locationId=` |
| Company (custom object record) | `POST /objects/{businessObjectId}/records` | `{locationId, properties:{name}}`. Update: `PUT /objects/{objId}/records/{id}?locationId=` `{properties:{domainname}}`. Delete: `DELETE /objects/{objId}/records/{id}`. Companies are the `business` object; its object id differs per location (`GET /objects/` lists them). A "Company Enrichment Automation" updates the record a second later on its own |
| Pipeline create | `POST /opportunities/pipelines` | `{name, locationId, colorRenderMode:"dot", stages:[{name, position, color, stageWinProbability, showInFunnel, showInPieChart}], showInFunnel, showInPieChart}` → `{pipeline:{id, stages[].id}}` |
| Pipeline edit | `PUT /opportunities/pipelines/{id}` | Full stages array, existing stages keep their `id`, new stages have none. Delete: `DELETE /opportunities/pipelines/{id}` |
| Product | `POST /products/` | `{locationId, name, productType:"DIGITAL", availableInStore:false, medias:[], variants:[], prices:[{name, type:"one_time", currency, amount, marginConfig:{enabled:false}}]}`. Update: `PUT /products/{id}` (prices keep `_id`). Delete: `DELETE /products/{id}?locationId=` |
| Workflow create | `POST /workflow/{loc}` | `{name, status:"draft", parentId:null, workflowData:{templates:[]}, allowMultiple:true, stopOnResponse:false, location_id, company_id, company_age, ...}` → `{id}` (a UUID) |
| Workflow publish | `PUT /workflow/{loc}/{wf}` | **Same full-payload PUT as a save, with `status:"published"`** and the current `version`. Unpublish = same with `status:"draft"`. The UI refuses to publish a workflow with no steps. Each save also POSTs `/{wf}/validate-workflows` and `/validate-assets` first |
| Tag create from a workflow | `POST /workflow/{loc}/tags/create` | `{tag}` → `OK` |
| Trigger | `POST /workflow/{loc}/trigger` | Confirms section 2: no query string, camelCase `workflowId`, then `PUT /workflow/{loc}/only-triggers/{wf}`. Tag trigger condition: `{operator:"index-of-true", field:"tagsAdded", value:"<tag>", id:"tag-added"}` |
| Workflow delete | `DELETE /workflow/{loc}/delete` | **Body** `{type:"workflow", workflowIds:[...], updatedBy:<userId>}` → `{deletedIds, failures}`. Bulk-capable. (The older single delete `DELETE /workflow/{loc}/{id}` still works for folders) |
| Tag delete | `DELETE /locations/{loc}/tags/{tagId}` | services host. Deleted tags are restorable for 2 months (UI text) |
| Funnel create | `POST /funnels/funnel/create` | `{locationId, name, type:"funnel"}` → `{id}`. The UI then calls `POST /funnels/builder/funnel-share-url` `{funnelId, shareWith:"ALL", companyId}` |
| Funnel step create | `POST /funnels/funnel/create-step` | `{step:{id:<new uuid>, name, url, pages:[], type:"optin_funnel_page", split:false, control_traffic:100}, funnelId}` → returns the new page (a Firestore `funnel_pages` doc) |
| Funnel delete | `POST /funnels/funnel/delete` | `{funnelId, locationId, userId}` (a POST, not DELETE) |
| Empty page save | autosave | The builder refuses to save a page with no sections ("No sections found... Aborting Save"): add at least one section first |
| Media folder | `POST /medias/folder` | `{name, parentId:"", altId:<loc>, altType:"location", mode:"public"}` |
| Media upload (3 steps) | `POST /medias/files/` → signed `PUT` → `POST /medias/files/verify` | 1: `{name, contentType, size, parentId:"", altType:"location", altId, mode:"public"}` returns a signed `storage.googleapis.com/msgsndr/...` URL. 2: PUT the raw bytes to that URL (no GHL headers). 3: `{altId, altType, id, mode}` marks it uploaded. Public URL: `https://assets.cdn.filesafe.space/{loc}/media/{fileId}.{ext}` |
| Media rename / details | `POST /medias/{fileId}` | `{name, altId, altType, tags:[...], description, altText}` |
| Media trash / delete forever | `PUT /medias/delete-files` | `{altId, altType, mode, lastUpdatedBy, status:"trashed"|"deleted", filesToBeDeleted:[{_id, altId, altType, ...}]}`. `"deleted"` = permanent. Trash auto-purges after 30 days |
| Media restore | `PUT /medias/update-files` | `{filesToBeUpdated:[{id, deleted:false, status:"restored", type}], altId, lastUpdatedBy, mode}` |
| Audit log | `GET /audit/search/v2?page=&pageSize=&startAt=&endAt=&locationId=[&documentType=PIPELINE]` | Every create/update/delete with who, when and a full before/after JSON. Covers pipelines, companies, notes and more, but **workflows are not a module here** |

## Pages that write when you only open them

Same family as the dashboard `preference` PUT in section 4. Harmless defaults, but they show up as writes in a HAR and in audit logs:

- Reputation opens: `POST /reputation/configs` (default dashboard card layout) and `POST /reputation/widgets/configs`.
- Client portal opens: `POST /clientclub/portal-settings` `{subDomain:<loc>, locationId}` (default subdomain).
- Reporting Google Ads / Meta Ads tabs: `PUT /locations/{loc}` `{googleAdsMarkupFee:0}` / `{facebookAdsMarkupFee:0}`.
- Email services page: `PUT /email-isv/feature/domain/lc-spf-record` `{domains:[]}`.
- External tracking page: `POST /external-tracking/` creates a tracking id if none exists.
- Every page: `POST /email-isv/set/status` and `POST /emails/schedule/location-email-provider` are reads sent as POSTs. `POST /cpaas/numbers/selection/voice` 400s on a location with no numbers; that is noise.

## Still not captured

- Snapshots (agency level: create from location, load into location, status).
- Contact create/import; tag bulk add/remove on contacts; tag category create.
- Conversation sending (deliberately skipped: no outbound sends from a test account).
- Workflow trigger delete, cross-location workflow copy, error-notification write.
- Website creation, funnel step reorder.
- Calendar delete, appointment book/reschedule/cancel, block-off times (calendar create is in `CALENDARS.md`).
- Users and teams (create, role, calendar assignment): only reads.
- Email sending setup writes (dedicated domain, DKIM/SPF, SMTP).
- AI agents / Conversation AI setup, social planner post create, invoice/estimate create, documents and contracts, course and community create, brand board writes, custom field conditional-rule writes, form version restore.
