# Calendars: build recipe

Create, configure, schedule and notify GHL calendars through the internal API. Endpoint list: [`ENDPOINTS.md`](ENDPOINTS.md) → Calendars. Run everything with `./ghl.sh -a <acct> raw|post|put <path> [<json-or-@file>]`; it sets the browser user-agent that Python urllib lacks (its default UA gets Cloudflare 1010). `./ghl.sh calendars <loc>` lists name, type, active flag and id.

Every write here follows the [`AGENTS.md`](AGENTS.md) safety contract: back up, show the user, confirm, then send.

## Gather first

Location id and account; calendar type; slot length, interval, buffers, seats per slot and per day, booking window; team members (one user, or several with priorities for round robin); standalone or in a group; weekly hours and timezone; which notification combos (type x channel x receiver).

## Build sequence

1. **Group (optional).** `POST /calendars/groups/validate-slug` `{locationId, slug}` -> `{available}`, then `POST /calendars/groups` `{name, description, slug, widgetType:"neo", locationId}` -> `{group:{id}}`.

2. **Validate the calendar slug.** `POST /calendars/validate-calendar-slug` `{calendarId:"", slug, groupId:""}` (groupId set when the calendar goes in a group). Slugs are unique per location for standalone calendars, per group for grouped ones.

3. **Create.** `POST /calendars/`:
   ```json
   {"name":"Discovery Call","description":"","slotDuration":30,"slotDurationUnit":"mins",
    "widgetSlug":"<slug>","locationId":"<loc>","calendarType":"personal",
    "showSeatsPerSlot":false,"stripe":{},
    "teamMembers":[{"userId":"<userId>","priority":0.5,"isZoomAdded":"false","zoomOauthId":"","selected":true}]}
   ```
   - `calendarType` values confirmed on create: `personal`; `round_robin` plus `"eventType":"RoundRobin_OptimizeForAvailability"`; `class_booking` (add `showSeatsPerSlot:true`). `collective`, `service` and `event` create bodies are unmapped.
   - `teamMembers` needs at least one entry, else 422 `teamMembers must contain at least 1 elements`. On a snapshot or builder subaccount with no location users (`GET /users/?locationId=<loc>` returns `[]`), use the agency/token user id as a placeholder; the buyer remaps it on import.
   - Round robin: one entry per user, `priority` 0 to 1 weights the rotation.

4. **Configure: GET, strip, modify, PUT.** The create response is sparse; all real configuration goes through `PUT /calendars/<id>`. PUT replaces the whole calendar, so send the full doc. The GET doc is not PUT-able as is: it carries server-managed keys the validator rejects. Strip `id, createdBy, dateAdded, dateUpdated, deleted, isSystemGenerated, lastUpdatedBy, locationId, order, version, notificationStatus, providerId`, and `openHours` when it is `{}` (an empty object fails with `must be a valid day of week` / `daysOfTheWeek must be an array`). If a 422 `property X should not exist` still comes back, pop X and retry (cap about 12 rounds).
   ```bash
   ./ghl.sh -a <acct> raw "/calendars/<calId>" | jq '(.calendar // .)
     | del(.id,.createdBy,.dateAdded,.dateUpdated,.deleted,.isSystemGenerated,.lastUpdatedBy,
           .locationId,.order,.version,.notificationStatus,.providerId)
     | if .openHours == {} then del(.openHours) else . end' > cal.json
   # edit cal.json, then:
   ./ghl.sh -a <acct> put "/calendars/<calId>" @cal.json
   ```
   Seat caps: the doc has both `appoinmentPerSlot` (GHL's typo) and `appointmentPerSlot`, and capacity follows the correctly spelled one. Set both to the cap, and likewise `appoinmentPerDay` and `appointmentPerDay`. Knob-to-field map below.

5. **Availability.** Default to `openHours` on the calendar with `enableOfficeHours:true`; it works on `personal` and `class_booking` and needs no schedule lookup:
   ```json
   "openHours":[{"daysOfTheWeek":[1],"hours":[{"openHour":9,"openMinute":0,"closeHour":17,"closeMinute":0}]},
                {"daysOfTheWeek":[2],"hours":[{"openHour":9,"openMinute":0,"closeHour":17,"closeMinute":0}]}]
   ```
   Days are Sun=0 to Sat=6, one block per day: a block with several days (`[1,2,3]`) is rejected with `openHours.0.must be a valid day of week`. `slotInterval` spaces the start times inside the window (Mon 9:00-10:45 at interval 60 gives 9:00 and 10:00). `class_booking` calendars always use `openHours` (they have `scheduleId:null`, `availabilities:[]`).

   Only for a calendar linked to a schedule (non-null `scheduleId`), update that schedule instead: `PUT /calendars/schedules/<scheduleId>` `{name, timezone, calendarIds:[<calId>], rules:[{day:"monday", type:"wday", intervals:[{from:"9:0", to:"17:0"}]}, ...]}`, one rule per weekday, `intervals: null` for a day off, several intervals for split shifts. Find the id with `GET /calendars/schedules/search?locationId=<loc>&isDefault=true` and match on `calendarIds`.

6. **Notifications.** `GET /calendars/event-notifications/list?altType=calendar&altId=<calId>` first: creation already adds contact and assignedUser confirmation emails. Each `(altId, altType, receiverType, channel, notificationType)` combo is unique; posting an existing combo, or updating one row onto another's combo, returns 400 Mongo E11000. Create the missing ones with `POST /calendars/event-notifications` and an array body:
   ```json
   [{"altType":"calendar","altId":"<calId>","receiverType":"contact","channel":"email",
     "notificationType":"reminder","isActive":true,"templateId":"",
     "subject":"Reminder: {{appointment.start_time}} ({{appointment.timezone}})","body":"<p>...</p>",
     "beforeTime":[{"timeOffset":24,"unit":"hours"}],"afterTime":[],
     "selectedUsers":[],"additionalEmailIds":[],"deleted":false}]
   ```
   `receiverType` contact|assignedUser, `channel` email|sms, `notificationType` confirmation|reminder|cancellation|reschedule|followup; `beforeTime` for reminders, `afterTime` for followups, blank `templateId` uses the inline body. Edit existing rows with `PUT /calendars/event-notifications/bulk-update` (array, `_id` on each row).

7. **Group placement.** `PUT /calendars/move-group` `{locationId, providerId:<groupId>, calendarIds:[...]}`.

8. **Activate.** Check `isActive` after create (a personal create has come back false, a round-robin create true) and set it with `PUT /calendars/<id>/status` `{isActive:true}`.

9. **Verify what can be booked** with `raw "/calendars/<calId>/free-slots?startDate=<epoch_ms>&endDate=<epoch_ms>&timezone=<tz>"`, not by reading `openHours`: round-robin per-member schedules are not stored on the calendar object, so its `openHours` can read empty while slots exist.

Build and configure only. Never test by booking through the public widget: a booking fires real confirmation emails and SMS.

## Config knobs

| What | Field |
|---|---|
| Slot length / spacing | `slotDuration` + `slotDurationUnit` (`mins`) / `slotInterval` + `slotIntervalUnit` |
| Buffer before / after | `preBuffer` + `preBufferUnit` / `slotBuffer` + `slotBufferUnit` |
| Earliest / latest booking | `allowBookingAfter` + `allowBookingAfterUnit` / `allowBookingFor` + `allowBookingForUnit` |
| Seats per slot / per day | both spellings: `appoinmentPerSlot` + `appointmentPerSlot`, `appoinmentPerDay` + `appointmentPerDay` |
| Auto-confirm | `autoConfirm: true` |
| Round-robin algorithm / weighting | `eventType: "RoundRobin_OptimizeForAvailability"` / `teamMembers[].priority` (0 to 1) |
| Recurring meeting | `enableRecurring: true` + `recurring: {freq:"WEEKLY", interval, count, weekDays:["MO"], monthDays:[], bookingOption:"skip"\|"book", bookingOverlapDefaultStatus}` |
| Look-busy | `lookBusyConfig: {enabled, lookBusyPercentage}` |
| Consent checkbox | `enableConsentCheck` + `consentLabel` |
| Guests | `enableGuests` + `guestType: "collect_detail"` + `enableMandatoryGuestType` |
| Sticky contact | `stickyContact` |
| After booking | `formSubmitType: ThankYouMessage\|RedirectURL`, `formSubmitThanksMessage`, `formSubmitRedirectURL` |
| Widget colours / logo | `widgetConfig.primarySettings.{primaryColor, backgroundColor, buttonText}` / `widgetLogo: {shape, url}` |
| Event title / colour | `eventTitle` (merge tags like `{{contact.name}}`) / `eventColor` |

## Gotchas

- Never name a bash variable `UID`: it is readonly (the OS uid, e.g. `1000`), so `UID=$(jq ...)` silently does nothing and the calendar API accepts `1000` as a bogus `teamMembers.userId`. Use `OWNER` or `AGENT_UID`.
- Keep GHL's `appoinment` spelling in field names; it is the real key.

Unmapped (capture a HAR on a sandbox location first): calendar delete, appointment book/reschedule/cancel, block-off times, separate schedule create, room/equipment create, external calendar OAuth.
