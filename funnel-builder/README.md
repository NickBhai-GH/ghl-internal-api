# Funnel page builder

Author **native drag-and-drop** GHL funnel pages via the internal API — the same JSON the
page editor produces, fully editable in the builder afterward (not custom-HTML/code blocks).

`funnel_page_builder.py` is a self-contained helper (templates embedded in `templates.json`,
no client data). Reverse-engineered from builder HARs on a sandbox sub-account.

## The two write endpoints

All on `backend.leadconnectorhq.com`, header **`version: 2021-07-28`** (NOT 2021-04-15 — the
builder uses a newer version), `channel: APP`, `source: WEB_USER`, plus a **browser
`User-Agent`** (Cloudflare 1010-bans `python-urllib`).

| Action | Call |
|---|---|
| Create step (+ its page) | `POST /funnels/funnel/create-step` — body `{"step":{"id":<uuid>,"name":..,"url":<slug>,"pages":[],"type":"optin_funnel_page","split":false,"control_traffic":100},"funnelId":..}` → returns new `pageId` |
| Read page | `GET /funnels/page/<pageId>?locationId=<loc>` → page doc with `pageDataDownloadUrl` (Firebase) + `pageVersion` |
| Save page | `POST /funnels/builder/autosave/<pageId>` (origin `https://page-builder.leadconnectorhq.com`) — body `{funnelId, pageData, pageVersion, pageType:"draft", manualSave:true, integrations:{…}}` |

`autosave` takes the **entire `pageData` inline** — the backend writes it to Firebase storage
itself and returns a fresh `pageDataDownloadUrl`. No signed-upload dance. Bump `pageVersion`
to `current + 1` on each save.

## The page JSON shape

`pageData = {sections[], settings, general, pageStyles, trackingCode, fontsForPreview, popups, popupsList}`

A **section** is `{id, metaData, elements[], sequence, pageId, funnelId, locationId, general}`.
The tree is **flat**: `section.elements` is a single list containing *all* rows + cols +
elements, linked by `child` id arrays (section.metaData.child → row ids; row.child → col ids;
col.child → element ids). It is NOT nested.

- **Element** (`meta` = heading/paragraph/button/image/rich-text/sub-heading/form/…):
  `{id, type:"element", meta, tagName, tag, extra, styles, wrapper, mobileStyles, child:[]}`.
  Text lives in `extra.text.value` (HTML). Font sizes in `extra.desktopFontSize` /
  `extra.mobileFontSize`. Color/weight/align/lineHeight/fontFamily in `styles`.
- **Section background image** → `section.metaData.extra.bgImage.value.url`. Custom-value
  tokens drop straight in: `"{{custom_values.hero_background}}"`. Use
  `options:"full-center"` for full-bleed cover (default is `"bgCover"`).
- **Multi-column** → set each col's `styles.width = {value:<pct>, unit:"%"}`. Cols stack to
  full width on mobile automatically.
- **Mobile** → per-element `mobileStyles` (e.g. `textAlign`, paddings) +
  `extra.visibility.value.hideMobile/hideDesktop`. `mobileFontSize` is separate from desktop.

## Saved colors (so they show in the UI picker)

Loose hex values do **not** appear in the builder's color picker. A reusable/saved color is:
1. an entry in `general.general.colors`: `{label:"color-<8>", value:"#rrggbbaa", name:"Brand Gold"}`
2. a `:root` CSS var in `pageStyles`: `--color-<8>: #rrggbbaa;`
3. referenced from elements as `var(--color-<8>)`

`reg_color()` + `build_page()` handle all three.

## Fonts (the tricky part)

The builder **authoritatively manages fonts** — it resets API-set `fontsToLoad` and
`settings.typography` back to defaults (Inter) on the next builder save. So you can't lock a
typeface through the page JSON alone. Two working routes:

1. **Inject via tracking code** (`inject_fonts()`): the builder *preserves* `trackingCode`.
   Add the original **Adobe Typekit kit** (`<link href="https://use.typekit.net/<kit>.css">`)
   and/or a Google `css2` link, then set element `fontFamily` to the real name
   (e.g. `cofo-raffine`, `calvino`, `Pontano Sans`). Typekit font files serve **200
   cross-domain**, so the exact fonts render in the GHL preview too, not just live.
2. **Upload as GHL custom fonts**: pull the `.woff2`/`.ttf` from the kit and upload via
   Settings/builder → *Add Custom Fonts*, naming the family **exactly** to match element
   `fontFamily`. (Extract weights from the kit's `@font-face` blocks; convert woff2→ttf with
   `fontTools` if the uploader rejects woff2.) Note these are **licensed** foundry fonts —
   self-hosting is the client's license call.

## Gotchas banked the hard way

- `find(type=="section")` matches `section.metaData` (which has `type:"section"`), not the
  section container — the container has no top-level `type`. Grab `pageData.sections[i]`.
- The section template carries whatever bg the source page had — always **explicitly clear**
  `bgImage.url` for solid-color sections or they inherit a stray background image.
- Two editors (you in the UI + a script via API) **clobber each other** on the same page.
  Pick one driver per page at a time.
- Scratch-build pattern: build into a throwaway funnel, then copy the step to the real funnel
  in the UI and delete the scratch one.

## Known limitation — API-created sections "bleed" in the builder (and the fix)

A section **created from scratch via the API** can render fine on the published/preview domain
but **bleed in the GHL builder UI** — its `position:fixed` `.bg-fixed` background layer escapes
the mobile frame and covers the editor. Root cause: GHL has the section's data but never
*registered* it through its own builder pipeline, so the editor can't contain it. No in-place
API tweak cures it (CSS dedupe, zero-CSS, adding `_id`, dimension audits — all still bleed).

The reliable workaround is a **Global-Section round-trip** — let GHL "bless" the section natively:

1. Create the **empty section shells in the builder UI** (correct column count per section).
   Sections a human creates are native and clean; API-*created* sections are what bleed.
2. **Inject only the content elements** into those native columns via `autosave` — clone GHL's
   own native heading/paragraph nodes (id-remap + patch their values), append to the target
   column's `child` + `section.elements` + `sectionStyles`, and merge the brand color vars +
   custom fonts into the page's `pageStyles`/`general` so `var(--color-*)` and fonts resolve.
   Injecting into a *native* section does **not** bleed.
3. Convert each populated section to a **Global Section** in the builder UI → this re-runs it
   through GHL's builder pipeline, re-registering/recompiling it natively (launders the API
   content into a first-class section).
4. Add the global section to a step → drops in clean → then onto the real funnel.

So the API does the tedious content population; the Global-Section round-trip makes it native.
Trying to compile the section CSS yourself is a dead end (renders on the preview domain, breaks
in the builder).

## Usage

See the module docstring for a runnable example. Set `B.ACCOUNT/LOC/FUNNEL`, build
sections, `build_page()`, optionally `inject_fonts()`, then `create_step()` + `autosave()`.
