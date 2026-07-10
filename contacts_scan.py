#!/usr/bin/env python3
"""
contacts_scan.py — paginate a GHL location's contacts via the internal
/contacts/search/2 endpoint, hydrate custom-field VALUES (which the endpoint
returns inline), optionally filter, and dump JSON/CSV.

Account-agnostic. Invoked by `ghl.sh contacts-scan` (which injects a fresh
token) but runnable standalone.

Key facts baked in (reverse-engineered from the internal API):
  * /contacts/search/2 DOES return customFields[] with values inline
    (each: {id, type, fieldValueString | fieldValueDate | fieldValue}).
    Older toolkit notes claiming customFields come back empty are STALE.
  * PAGE-BASED pagination works: body {locationId, page, pageLimit:100,
    sort:[], filters:[]}, page 1..N. Tested to depth 81 (8k contacts).
  * The searchAfter cursor form 400s with the default (empty) sort, and a
    `sort:[{field:"dateAdded"...}]` clause 422s ("invalid field") — so just
    walk pages. total is returned on every response.
  * Browser User-Agent is required or Cloudflare 403s bare clients.
DATE custom fields come back as epoch-millis under fieldValueDate; we decode
them to YYYY-MM-DD (GHL stores DATE truncated to midnight UTC anyway).
"""
import argparse, csv, json, math, sys, urllib.request, urllib.error
import concurrent.futures as cf
from datetime import datetime, timezone


def build_headers(token):
    return {
        "token-id": token, "channel": "APP", "version": "2021-04-15",
        "source": "WEB_USER",
        "origin": "https://client-app-automation-workflows.leadconnectorhq.com",
        "user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "content-type": "application/json",
        "accept": "application/json, text/plain, */*",
    }


def http_json(url, headers, data=None, tries=3):
    body = json.dumps(data).encode() if data is not None else None
    last = None
    for _ in range(tries):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code}: {e.read()[:200].decode(errors='replace')}"
        except Exception as e:  # noqa
            last = str(e)
    raise RuntimeError(last)


def field_maps(api, headers, loc):
    """Return (id->name, name_lower->id) for contact custom fields."""
    d = http_json(f"{api}/locations/{loc}/customFields?model=contact", headers)
    fs = d.get("customFields") or d.get("customField") or []
    id2name, name2id, id2type = {}, {}, {}
    for f in fs:
        id2name[f["id"]] = f["name"]
        name2id[f["name"].lower()] = f["id"]
        id2type[f["id"]] = f.get("dataType", "")
    return id2name, name2id, id2type


def cf_value(entry, ftype=""):
    """Extract a scalar value from a customFields[] entry, decoding dates."""
    if "fieldValueDate" in entry and entry["fieldValueDate"] not in (None, ""):
        v = entry["fieldValueDate"]
        try:
            ms = int(v)
            return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            return v
    for k in ("fieldValueString", "fieldValue", "fieldValueNumber", "fieldValueArray"):
        if k in entry and entry[k] not in (None, ""):
            return entry[k]
    return None


def resolve_cf(contact, id2name, id2type):
    out = {}
    for e in contact.get("customFields", []):
        fid = e.get("id")
        if not fid:
            continue
        out[id2name.get(fid, fid)] = cf_value(e, id2type.get(fid, ""))
    return out


def parse_where(clauses, name2id):
    """['Field Name~sub', 'Other=val'] -> [(field_name, op, value)]."""
    parsed = []
    for c in clauses:
        if "~" in c:
            name, val, op = *c.split("~", 1), "contains"
        elif "=" in c:
            name, val, op = *c.split("=", 1), "equals"
        else:
            sys.exit(f"bad --where '{c}' (use 'Field~substr' or 'Field=value')")
        if name.lower() not in name2id:
            sys.exit(f"unknown field name in --where: '{name}'. "
                     f"Run with --list-fields to see available names.")
        parsed.append((name, op, val))
    return parsed


def matches(cfvals, wheres):
    for name, op, val in wheres:
        cur = cfvals.get(name)
        cur_s = "" if cur is None else str(cur)
        if op == "contains" and val.lower() not in cur_s.lower():
            return False
        if op == "equals" and cur_s.lower() != val.lower():
            return False
    return True


def main():
    ap = argparse.ArgumentParser(description="Scan GHL contacts + hydrate custom fields.")
    ap.add_argument("--token", required=True)
    ap.add_argument("--api", default="https://backend.leadconnectorhq.com")
    ap.add_argument("--loc", required=True, help="locationId")
    ap.add_argument("--where", action="append", default=[],
                    help="filter 'Field Name~substr' (contains) or 'Field Name=value' (exact). Repeatable (AND).")
    ap.add_argument("--select", default="",
                    help="comma-separated custom-field NAMES to include in output/table. Default: all.")
    ap.add_argument("--out", help="write full matched contacts as JSON array")
    ap.add_argument("--csv", help="write matched contacts as CSV (id,name,phone,email + selected fields)")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--max-pages", type=int, default=0, help="cap pages (0 = all)")
    ap.add_argument("--list-fields", action="store_true", help="print custom-field names+ids and exit")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args()

    H = build_headers(a.token)
    id2name, name2id, id2type = field_maps(a.api, H, a.loc)

    if a.list_fields:
        for fid, nm in sorted(id2name.items(), key=lambda x: x[1].lower()):
            print(f"{id2type.get(fid,''):<14} {fid:<24} {nm}")
        return

    wheres = parse_where(a.where, name2id)
    select = [s.strip() for s in a.select.split(",") if s.strip()]

    url = f"{a.api}/contacts/search/2"
    first = http_json(url, H, {"locationId": a.loc, "page": 1, "pageLimit": 100, "sort": [], "filters": []})
    total = first.get("total", 0)
    pages = math.ceil(total / 100) if total else 1
    if a.max_pages:
        pages = min(pages, a.max_pages)

    def get_page(pg):
        if pg == 1:
            return first.get("contacts", [])
        d = http_json(url, H, {"locationId": a.loc, "page": pg, "pageLimit": 100, "sort": [], "filters": []})
        return d.get("contacts", [])

    matched, scanned = [], 0
    with cf.ThreadPoolExecutor(max_workers=a.workers) as ex:
        for cs in ex.map(get_page, range(1, pages + 1)):
            scanned += len(cs)
            for c in cs:
                cfv = resolve_cf(c, id2name, id2type)
                if matches(cfv, wheres):
                    matched.append({
                        "id": c.get("id"),
                        "name": c.get("contactName"),
                        "email": c.get("email"),
                        "phone": c.get("phone"),
                        "tags": c.get("tags", []),
                        "customFields": cfv if not select else {k: cfv.get(k) for k in select},
                    })

    if not a.quiet:
        print(f"scanned {scanned}/{total} contacts over {pages} pages; matched {len(matched)}", file=sys.stderr)
        if matched and select:
            pop = {k: sum(1 for m in matched if m["customFields"].get(k) not in (None, "")) for k in select}
            print("field population among matched: " +
                  ", ".join(f"{k}={v}/{len(matched)}" for k, v in pop.items()), file=sys.stderr)

    if a.out:
        json.dump(matched, open(a.out, "w"), indent=1)
        if not a.quiet:
            print(f"wrote {a.out}", file=sys.stderr)
    if a.csv:
        cols = ["id", "name", "email", "phone"] + (select or sorted({k for m in matched for k in m["customFields"]}))
        with open(a.csv, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(cols)
            for m in matched:
                w.writerow([m["id"], m["name"], m["email"], m["phone"]] +
                           [m["customFields"].get(k, "") for k in (select or cols[4:])])
        if not a.quiet:
            print(f"wrote {a.csv}", file=sys.stderr)
    if not a.out and not a.csv:
        json.dump(matched, sys.stdout, indent=1)
        print()


if __name__ == "__main__":
    main()
