#!/usr/bin/env python3
"""
GHL funnel page builder — author native drag-and-drop funnel pages via the internal API.

Builds the same JSON the GHL page editor produces (sections -> rows -> cols -> elements,
flattened into one `elements` list linked by `child` ids), then creates a step and saves
the page through the builder's autosave endpoint. Pages built this way are fully editable
in the GHL builder afterward — they are NOT custom-HTML/code blocks.

Endpoints used (all on backend.leadconnectorhq.com, header `version: 2021-07-28`):
  POST /funnels/funnel/create-step            -> create a step + its page, returns pageId
  GET  /funnels/page/<pageId>?locationId=     -> page doc (has pageDataDownloadUrl + pageVersion)
  POST /funnels/builder/autosave/<pageId>     -> save full pageData inline (manualSave:true)

Auth: reuses the toolkit's account tokens (accounts/<name>/token.txt via ghl.sh refresh).
A browser User-Agent is REQUIRED — Cloudflare 1010-bans the default python-urllib UA.

Quick start:
    import funnel_page_builder as B
    B.ACCOUNT, B.LOC, B.FUNNEL = "myaccount", "<locationId>", "<funnelId>"
    tok = B.token()
    GREEN = B.reg_color("Brand Green", "#3d4940ff")
    h = B.heading("<h1>Thank You!</h1>", B.reg_color("Gold","#b3ac80ff"), 70, 42, 500,
                  "cofo-raffine", align="left"); B.tweak(h, mobile_align="center", lineheight=1.4)
    p = B.paragraph("<p>Your form submission has been submitted.</p>", "var(--white)", 18, 16, 400, "Pontano Sans")
    col = B.col([h, p], bg=GREEN, pad=(90,56,110,56), width=56, mobilepad=(44,26,52,26))
    sec = B.section([B.row([col])], 1, bgimg="{{custom_values.hero_background}}",
                    pad=(100,0,100,0), mobilepad=(60,0,60,0))
    page = B.build_page([sec])
    B.inject_fonts(page, head_link='<link rel="stylesheet" href="https://use.typekit.net/<kit>.css">')
    st, resp, sid = B.create_step(tok, "Thank You", "thank-you")
    pageId = resp["page"]["_id"]
    B.autosave(tok, pageId, page, resp["page"]["_data"]["page_version"] + 1)
"""
import json, copy, os, random, string, subprocess, urllib.request, urllib.error

# ---- configure these (or set after import) ----
TOOLKIT  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # repo root (has ghl.sh)
ACCOUNT  = "myaccount"   # accounts/<ACCOUNT>/ under the toolkit
LOC      = ""            # locationId
FUNNEL   = ""            # funnelId to build into

API = "https://backend.leadconnectorhq.com"
UA  = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

_T = json.load(open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "templates.json")))

# ---------------- auth + transport ----------------
def token():
    subprocess.run(["./ghl.sh", "-a", ACCOUNT, "refresh"], cwd=TOOLKIT, capture_output=True)
    return open(f"{TOOLKIT}/accounts/{ACCOUNT}/token.txt").read().strip()

def _hdrs(tok, origin="https://wrm.enrolltoday.education"):
    return {"token-id": tok, "channel": "APP", "version": "2021-07-28", "source": "WEB_USER",
            "origin": origin, "content-type": "application/json",
            "accept": "application/json, text/plain, */*", "user-agent": UA}

def req(method, url, tok, body=None, origin="https://wrm.enrolltoday.education"):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(url, data=data, method=method, headers=_hdrs(tok, origin))
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

def fetch_pagedata(tok, pageId):
    """Return (pageVersion, pageData dict) for an existing page."""
    st, doc = req("GET", f"{API}/funnels/page/{pageId}?locationId={LOC}", tok)
    r = urllib.request.Request(doc["pageDataDownloadUrl"], headers={"user-agent": UA})
    pd = json.loads(urllib.request.urlopen(r, timeout=60).read().decode())
    return doc.get("pageVersion", 1), pd

# ---------------- id helper ----------------
def rid(prefix):
    return prefix + "-" + "".join(random.choices(string.ascii_letters + string.digits, k=10))

# ---------------- saved colors (appear in the UI palette) ----------------
# GHL stores reusable colors in general.colors as {label,value,name} + a :root --<label> var,
# referenced from elements as var(--<label>). Loose hex values do NOT show in the picker.
PALETTE = []
def reg_color(name, hex8):
    """Register a saved palette color. hex8 = 8-digit #rrggbbaa. Returns a 'var(--...)' ref."""
    label = "color-" + "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    PALETTE.append({"label": label, "value": hex8, "name": name})
    return f"var(--{label})"

# ---------------- element / layout builders ----------------
def tweak(e, mobile_align=None, lineheight=None, lh_unit="em", italic=False, ls=None, upper=False):
    if mobile_align: e.setdefault("mobileStyles", {})["textAlign"] = {"value": mobile_align}
    if lineheight is not None: e["styles"]["lineHeight"] = {"value": lineheight, "unit": lh_unit}
    if ls is not None: e["styles"]["letterSpacing"] = {"value": str(ls), "unit": "px"}
    if upper: e["styles"]["textTransform"] = {"value": "uppercase"}
    if italic: e["styles"]["fontStyle"] = {"value": "italic"}
    return e

def heading(html, color, d_px, m_px, weight, family, align="center", tag="h1"):
    e = copy.deepcopy(_T["heading"]); i = rid("heading"); e["id"] = i; e["extra"]["nodeId"] = i
    e["extra"]["text"] = {"value": html}
    e["extra"]["desktopFontSize"] = {"value": d_px, "unit": "px"}
    e["extra"]["mobileFontSize"] = {"value": m_px, "unit": "px"}
    e["styles"]["color"] = {"value": color}
    e["styles"]["fontFamily"] = {"value": family}
    e["styles"]["fontWeight"] = {"value": "normal", "desktop": str(weight)}
    e["styles"]["textAlign"] = {"value": align}
    e["tag"] = tag
    return e

def paragraph(html, color, d_px, m_px, weight, family, align="center"):
    e = copy.deepcopy(_T["paragraph"]); i = rid("paragraph"); e["id"] = i; e["extra"]["nodeId"] = i
    e["extra"]["text"] = {"value": html}
    e["extra"]["desktopFontSize"] = {"value": d_px, "unit": "px"}
    e["extra"]["mobileFontSize"] = {"value": m_px, "unit": "px"}
    e["styles"]["color"] = {"value": color}
    e["styles"]["fontFamily"] = {"value": family}
    e["styles"]["fontWeight"] = {"value": "normal", "desktop": str(weight)}
    e["styles"]["textAlign"] = {"value": align}
    if "typography" in e["extra"]: e["extra"]["typography"] = {"value": "var(--contentfont)"}
    return e

def col(children, bg="var(--transparent)", pad=(20, 20, 20, 20), width=100, radius="0px",
        mobilepad=None, border=None):
    c = copy.deepcopy(_T["col"]); c["id"] = rid("col"); c["_kids"] = children
    pt, pr, pb, pl = pad
    c["styles"]["paddingTop"] = {"value": pt, "unit": "px"}
    c["styles"]["paddingRight"] = {"value": pr, "unit": "px"}
    c["styles"]["paddingBottom"] = {"value": pb, "unit": "px"}
    c["styles"]["paddingLeft"] = {"value": pl, "unit": "px"}
    c["styles"]["backgroundColor"] = {"value": bg}
    c["styles"]["background"] = {"value": "none"}
    c["styles"]["borderRadius"] = {"value": radius}
    c["styles"]["width"] = {"value": width, "unit": "%"}
    if border:
        bw, bs, bc = border
        c["styles"]["borderWidth"] = {"value": bw}
        c["styles"]["borderStyle"] = {"value": bs}
        c["styles"]["borderColor"] = {"value": bc}
    if mobilepad:
        mpt, mpr, mpb, mpl = mobilepad
        c["mobileStyles"] = {"paddingTop": {"value": mpt, "unit": "px"},
                             "paddingRight": {"value": mpr, "unit": "px"},
                             "paddingBottom": {"value": mpb, "unit": "px"},
                             "paddingLeft": {"value": mpl, "unit": "px"}}
    return c

def row(cols, align="center"):
    r = copy.deepcopy(_T["row"]); r["id"] = rid("row"); r["_kids"] = cols
    r["class"]["alignRow"] = {"value": f"row-align-{align}"}
    return r

def section(rows, seq, bgimg=None, bgcolor="var(--transparent)", pad=(80, 0, 80, 0), mobilepad=None):
    s = copy.deepcopy(_T["section"]); i = rid("section"); s["id"] = i; s["metaData"]["id"] = i
    s["metaData"]["child"] = [r["id"] for r in rows]
    pt, pr, pb, pl = pad
    st = s["metaData"]["styles"]
    st["paddingTop"] = {"value": pt, "unit": "px"};  st["paddingRight"] = {"value": pr, "unit": "px"}
    st["paddingBottom"] = {"value": pb, "unit": "px"}; st["paddingLeft"] = {"value": pl, "unit": "px"}
    st["backgroundColor"] = {"value": bgcolor}
    if mobilepad:
        mpt, _, mpb, _ = mobilepad
        s["metaData"]["mobileStyles"] = {"paddingTop": {"value": mpt, "unit": "px"},
                                         "paddingBottom": {"value": mpb, "unit": "px"}}
    # bgImage: always written; empty url == no image. Custom value tokens go straight in `url`.
    s["metaData"]["extra"]["bgImage"] = {"value": {"mediaType": "image", "url": (bgimg or ""),
        "opacity": "1", "options": "full-center", "svgCode": "", "videoUrl": "",
        "videoThumbnail": "", "videoLoop": True, "showSvgToggle": False}}
    # FLATTEN: section.elements is a flat list of rows + cols + elements, linked by child ids.
    flat = []
    for r in rows:
        cols = r.pop("_kids"); r["child"] = [c["id"] for c in cols]; flat.append(r)
        for c in cols:
            kids = c.pop("_kids"); c["child"] = [e["id"] for e in kids]; flat.append(c)
            for e in kids:
                e["child"] = e.get("child", []); flat.append(e)
    s["elements"] = flat; s["sequence"] = seq
    s["pageId"] = ""; s["funnelId"] = FUNNEL; s["locationId"] = LOC
    return s

# ---------------- page assembly ----------------
def build_page(sections, headfont="cofo-raffine", bodyfont="Pontano Sans"):
    pd = copy.deepcopy(_T["envelope"])
    pd["sections"] = sections; pd["popups"] = []; pd["popupsList"] = []
    pd["fontsForPreview"] = [f"'{headfont}'", f"'{bodyfont}'"]
    g = pd["general"]["general"]
    g["fontsToLoad"] = [bodyfont]; g["fontsToLoadForPreview"] = [bodyfont]
    if PALETTE:
        g["colors"] = g.get("colors", []) + [dict(c) for c in PALETTE]
        vars_css = "".join(f"--{c['label']}: {c['value']};" for c in PALETTE)
        ps = pd.get("pageStyles", "")
        ps = ps.replace(":root{", ":root{" + vars_css, 1) if ":root{" in ps else ":root{" + vars_css + "}\n" + ps
        pd["pageStyles"] = ps; g["pageStyles"] = ps
    return pd

def inject_fonts(pageData, head_link):
    """Load fonts the builder can't manage (Adobe Typekit kit, Google css2) via the page <head>.
    The builder STRIPS API-set fontsToLoad/typography back to defaults, but it preserves
    trackingCode. Typekit font files (use.typekit.net/<kit>.css) serve 200 cross-domain, so the
    exact original fonts render in the GHL preview too. Set element fontFamily to match
    (e.g. 'cofo-raffine'). NOTE: GHL can also upload these as custom fonts (Settings/builder ->
    Add Custom Fonts) — name the family exactly to match the element fontFamily."""
    pageData["trackingCode"] = {"head": head_link, "body": ""}
    return pageData

# ---------------- writes ----------------
def create_step(tok, name, slug):
    import uuid
    sid = str(uuid.uuid4())
    body = {"step": {"id": sid, "name": name, "url": slug, "pages": [], "type": "optin_funnel_page",
                     "split": False, "control_traffic": 100}, "funnelId": FUNNEL}
    st, resp = req("POST", f"{API}/funnels/funnel/create-step", tok, body)
    return st, resp, sid

def autosave(tok, pageId, pageData, pageVersion):
    body = {"funnelId": FUNNEL, "pageData": pageData, "pageVersion": pageVersion, "pageType": "draft",
            "manualSave": True, "integrations": {"videoBackground": False,
            "blogMeta": {"selectedBlogCategories": [], "categoryNavigationList": []},
            "heading": 1, "popup": False}}
    return req("POST", f"{API}/funnels/builder/autosave/{pageId}", tok, body,
               origin="https://page-builder.leadconnectorhq.com")
