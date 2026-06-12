#!/usr/bin/env python3
"""
Build a Workflow Audit xlsx (one-sheet-per-workflow audit format) from local JSON dumps.

One sheet per workflow:
  Row 1: workflow name (col A)
  Header rows (col B/C): Status, Enrolled, Folder
  TRIGGERS section (T1..Tn)
  WORKFLOW STEPS section (numbered, branches as PATH headers)
  NOTES section (blank rows)

Reads:
  workflows/<loc>/<wf>.json     (workflow content)
  reports/<loc>-triage.csv      (status, total/active enrollment, folder)

Writes:
  reports/<loc>-audit.xlsx
"""

import csv, json, os, sys, re
from collections import defaultdict
import openpyxl
from openpyxl.styles import Font, Alignment, PatternFill

DIR = os.path.dirname(os.path.abspath(__file__))


# ---- attribute renderers ---------------------------------------------------

MERGE_FIELD_RE = re.compile(r"\{\{[^}]+\}\}")
HTML_TAG_RE = re.compile(r"<[^>]+>")


def html_to_text(s):
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"</p>", "\n", s, flags=re.I)
    s = HTML_TAG_RE.sub("", s)
    return s.strip()


def slashed(parts):
    return " / ".join(p for p in parts if p)


def render_attributes(node):
    """Return a human-readable summary of a node's attributes."""
    attrs = node.get("attributes") or {}
    t = node.get("type", "")

    if t == "email":
        return slashed([
            f"From Name: {attrs.get('from_name','')}",
            f"From Email: {attrs.get('from_email','')}",
            f"Subject: \"{attrs.get('subject','')}\"",
            (f"Body: {html_to_text(attrs.get('html',''))[:300]}" if attrs.get('html') else ""),
            (f"Attachments: {len(attrs.get('attachments') or [])}" if attrs.get('attachments') else ""),
        ])

    if t == "sms":
        return slashed([
            f"Message: \"{attrs.get('message','')}\"",
            (f"Attachments: {len(attrs.get('attachments') or [])}" if attrs.get('attachments') else ""),
        ])

    if t == "internal_notification":
        return slashed([
            f"Type: {attrs.get('type','').title()}",
            f"To: {attrs.get('to', attrs.get('email',''))}",
            f"From Name: {attrs.get('fromName', attrs.get('from_name',''))}",
            f"From Email: {attrs.get('fromEmail', attrs.get('from_email',''))}",
            f"Subject: \"{attrs.get('subject','')}\"" if attrs.get('subject') else "",
            f"Body: {html_to_text(attrs.get('body', attrs.get('html','')))[:200]}" if attrs.get('body') or attrs.get('html') else "",
        ])

    if t == "wait":
        sa = attrs.get("startAfter") or {}
        if sa.get("type") and sa.get("value") is not None:
            unit = sa["type"]
            val = sa["value"]
            # normalize: "hour"/24 -> "1 day", "days"/2 -> "2 days"
            if unit == "hour" and val % 24 == 0:
                d = val // 24
                return f"Wait {d} day{'s' if d != 1 else ''}"
            return f"Wait {val} {unit}{'s' if val != 1 and not unit.endswith('s') else ''}"
        if attrs.get("type") == "specific_day_time":
            return f"Wait until specific day/time: {attrs.get('day','')} {attrs.get('time','')}"
        return f"Wait (type={attrs.get('type','')})"

    if t == "add_contact_tag":
        tags = attrs.get("tags") or []
        return "Tags:\n" + "\n".join(f"- \"{tag}\"" for tag in tags) if tags else "(no tags)"

    if t == "remove_contact_tag":
        tags = attrs.get("tags") or []
        return "Removes tag(s):\n" + "\n".join(f"- \"{tag}\"" for tag in tags) if tags else "(no tags)"

    if t == "webhook":
        return slashed([
            f"Method: {attrs.get('method','POST')}",
            f"URL: {attrs.get('url','')}",
            f"Headers: {len(attrs.get('headers') or [])}",
            f"CustomData: {len(attrs.get('customData') or [])}",
        ])

    if t == "slack_message":
        return slashed([
            f"Action: {(attrs.get('action') or {}).get('name','')}",
            f"Channel: #{(attrs.get('channel') or {}).get('name','')}",
            f"Integration: {(attrs.get('integration') or {}).get('name','')}",
            f"Text: \"{attrs.get('text','')}\"",
        ])

    if t == "if_else":
        # condition node — branches contain the actual logic
        branches = attrs.get("branches") or []
        if not branches:
            return f"Condition: {attrs.get('conditionName','')} ({attrs.get('operator','and')})"
        lines = [f"Condition: {attrs.get('conditionName','')} ({attrs.get('operator','and')})"]
        for b in branches:
            cond = b.get("condition") or b.get("filters") or b
            lines.append(f"- {json.dumps(cond, default=str)[:140]}")
        return "\n".join(lines)

    if t == "update_contact_field":
        fields = attrs.get("fields") or []
        return "\n".join(f"- {f.get('title') or f.get('field')}: {f.get('value','')}" for f in fields)

    if t == "dnd_contact":
        return slashed([
            f"Direction: {attrs.get('direction','').title()}",
            f"DND: {attrs.get('action','').title()} for {attrs.get('channels','all channels')}",
        ])

    if t in ("mark_as_read", "mark_unread", "archive_conversation"):
        return t.replace("_", " ").title()

    if t == "delete_contact":
        return "Permanently deletes the contact from the account and all workflows."

    # fallback: dump the attributes
    return json.dumps(attrs, default=str, indent=None)[:400]


# ---- tree traversal --------------------------------------------------------

def build_tree(templates):
    """Map id -> node, parent -> [child_ids in `next` order]."""
    by_id = {n["id"]: n for n in templates}
    children = defaultdict(list)
    roots = []
    for n in templates:
        p = n.get("parent")
        if p and p in by_id:
            children[p].append(n["id"])
        else:
            roots.append(n["id"])
    # Sort children by `order` (then by name as tiebreak)
    for k in children:
        children[k].sort(key=lambda nid: (by_id[nid].get("order", 0), by_id[nid].get("name", "")))
    return by_id, children, roots


def walk_main_flow(by_id, children, roots):
    """Walk the linear main flow following `next` pointers from each root.
    Returns ordered list of (node, path-letter or None for main, depth)."""
    ordered = []
    visited = set()

    def walk(node_id, depth=0):
        if node_id in visited:
            return
        visited.add(node_id)
        node = by_id[node_id]
        ordered.append((node, depth))
        # For if_else: emit branches as path headers via siblings
        nxt = node.get("next")
        if nxt and nxt in by_id:
            walk(nxt, depth)

    for r in roots:
        walk(r)
    return ordered


# ---- xlsx writer -----------------------------------------------------------

HEAD_FONT = Font(bold=True, size=12)
SECTION_FONT = Font(bold=True, color="FFFFFF")
SECTION_FILL = PatternFill("solid", fgColor="404040")
PATH_FONT = Font(bold=True, color="000000")
PATH_FILL = PatternFill("solid", fgColor="D9E1F2")
WRAP = Alignment(wrap_text=True, vertical="top")


def safe_sheet_name(name):
    bad = '[]:*?/\\\''
    out = "".join("_" if c in bad else c for c in name)
    return out[:31]  # xlsx max sheet name length


def fmt_int(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return ""


def write_workflow_sheet(wb, wf_meta, wf_json):
    name = wf_meta["name"]
    ws = wb.create_sheet(safe_sheet_name(name))
    ws.column_dimensions["A"].width = 18
    ws.column_dimensions["B"].width = 28
    ws.column_dimensions["C"].width = 110

    # Header
    ws.cell(row=1, column=1, value=name).font = HEAD_FONT
    ws.cell(row=2, column=2, value="Status")
    ws.cell(row=2, column=3, value=wf_meta["status"].title())
    ws.cell(row=3, column=2, value="Enrolled")
    ws.cell(row=3, column=3, value=f"{fmt_int(wf_meta['total_enrolled'])} total | {fmt_int(wf_meta['currently_enrolled'])} active")
    ws.cell(row=4, column=2, value="Folder")
    ws.cell(row=4, column=3, value=wf_meta.get("folder", ""))

    row = 6

    # TRIGGERS
    triggers = wf_json.get("triggers") or wf_json.get("workflowTriggers") or []
    if triggers:
        c = ws.cell(row=row, column=1, value="TRIGGERS")
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        row += 1
        for i, trg in enumerate(triggers, 1):
            ws.cell(row=row, column=1, value=f"T{i}")
            ws.cell(row=row, column=2, value=trg.get("name") or trg.get("type") or "")
            cfg_lines = []
            if trg.get("type"):
                cfg_lines.append(f"Type: {trg['type']}")
            for k in ("filters", "conditions", "data", "config"):
                if trg.get(k):
                    cfg_lines.append(f"{k.title()}: {json.dumps(trg[k], default=str)[:300]}")
            cell = ws.cell(row=row, column=3, value=" / ".join(cfg_lines))
            cell.alignment = WRAP
            row += 1
        row += 1

    # WORKFLOW STEPS
    templates = (wf_json.get("workflowData") or {}).get("templates") or []
    if templates:
        c = ws.cell(row=row, column=1, value="WORKFLOW STEPS")
        c.font = SECTION_FONT; c.fill = SECTION_FILL
        row += 1

        by_id = {n["id"]: n for n in templates}
        emitted = set()

        def emit_step(node, label):
            nonlocal row
            emitted.add(node["id"])
            ws.cell(row=row, column=1, value=label)
            ws.cell(row=row, column=2, value=node.get("name") or node.get("type", ""))
            cell = ws.cell(row=row, column=3, value=render_attributes(node))
            cell.alignment = WRAP
            row += 1

        def emit_path_header(label):
            nonlocal row
            c = ws.cell(row=row, column=1, value=label)
            c.font = PATH_FONT; c.fill = PATH_FILL
            row += 1

        def emit_end():
            nonlocal row
            ws.cell(row=row, column=2, value="END")
            row += 1

        def walk(start_id, num_path):
            """Walk linearly from start_id. num_path is list of ints for hierarchy (e.g., [1,2,3] -> '1.2.3')."""
            cur = start_id
            step = 1
            while cur and cur in by_id and cur not in emitted:
                node = by_id[cur]
                label = ".".join(str(x) for x in (num_path + [step]))
                emit_step(node, label)

                nxt = node.get("next")
                t = node.get("type", "")

                if isinstance(nxt, list):
                    if t == "if_else":
                        for i, branch_id in enumerate(nxt, 1):
                            branch = by_id.get(branch_id)
                            if not branch:
                                continue
                            branch_name = (branch.get("name") or "").strip() or f"Branch {i}"
                            emit_path_header(f"PATH {chr(64+i)}: {branch_name}")
                            emitted.add(branch_id)  # branch wrapper itself is the label, content is its `next`
                            branch_first = branch.get("next")
                            if isinstance(branch_first, str):
                                walk(branch_first, num_path + [step, i])
                            elif isinstance(branch_first, list):
                                # Branch immediately starts with another decision (rare)
                                for j, b in enumerate(branch_first, 1):
                                    walk(b, num_path + [step, i, j])
                            emit_end()
                        return  # branching ends this chain
                    elif t == "find_opportunity":
                        labels = {0: "FOUND", 1: "NOT FOUND"}
                        for i, child_id in enumerate(nxt):
                            emit_path_header(f"PATH {labels.get(i, str(i+1))}")
                            walk(child_id, num_path + [step, i+1])
                            emit_end()
                        return
                    else:
                        # Generic branching: emit each as a numbered path
                        for i, child_id in enumerate(nxt, 1):
                            emit_path_header(f"PATH {i}")
                            walk(child_id, num_path + [step, i])
                            emit_end()
                        return
                elif isinstance(nxt, str):
                    cur = nxt
                    step += 1
                else:
                    return

        # Roots = nodes whose parent isn't another node in this workflow
        roots = [n["id"] for n in templates if not n.get("parent") or n["parent"] not in by_id]
        # Order roots by their numeric `order` if available
        roots.sort(key=lambda nid: by_id[nid].get("order", 0))

        main_step = 1
        for rid in roots:
            walk(rid, [main_step])
            main_step += 1

        # Orphans
        orphans = [nid for nid in by_id if nid not in emitted]
        if orphans:
            row += 1
            c = ws.cell(row=row, column=1, value="(unreached nodes — orphans or disconnected)")
            c.font = Font(italic=True, color="888888")
            row += 1
            for nid in orphans:
                emit_step(by_id[nid], "?")

        row += 1

    # NOTES
    c = ws.cell(row=row, column=1, value="NOTES")
    c.font = SECTION_FONT; c.fill = SECTION_FILL
    row += 1
    for _ in range(5):
        row += 1


# ---- main ------------------------------------------------------------------

def main(loc):
    triage_path = os.path.join(DIR, "reports", f"{loc}-triage.csv")
    if not os.path.exists(triage_path):
        sys.exit(f"missing {triage_path}; run: ./ghl.sh triage {loc}")

    wb = openpyxl.Workbook()
    # Build INDEX as the first sheet
    idx = wb.active
    idx.title = "INDEX"
    idx.append(["Workflow", "Status", "Total Enrolled", "Active", "Folder", "Tab"])
    idx["A1"].font = HEAD_FONT
    idx.column_dimensions["A"].width = 60
    idx.column_dimensions["E"].width = 50

    rows = list(csv.DictReader(open(triage_path)))
    rows.sort(key=lambda r: (r.get("folder") or "", r["name"].lower()))

    written = 0
    for r in rows:
        wid = r["workflow_id"]
        wf_path = os.path.join(DIR, "workflows", loc, f"{wid}.json")
        if not os.path.exists(wf_path):
            print(f"skip (no dump): {r['name']}", file=sys.stderr)
            continue
        with open(wf_path) as f:
            wf_json = json.load(f)
        meta = {
            "name": r["name"],
            "status": r["status"],
            "total_enrolled": int(r.get("total_enrolled") or 0),
            "currently_enrolled": int(r.get("currently_enrolled") or 0),
            "folder": r.get("folder", ""),
        }
        write_workflow_sheet(wb, meta, wf_json)
        idx.append([
            r["name"], r["status"].title(),
            meta["total_enrolled"], meta["currently_enrolled"],
            r.get("folder", ""),
            safe_sheet_name(r["name"]),
        ])
        written += 1

    out = os.path.join(DIR, "reports", f"{loc}-audit.xlsx")
    wb.save(out)
    print(f"wrote {out}  ({written} sheets)", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: export_xlsx.py <location_id>")
    main(sys.argv[1])
