#!/usr/bin/env python3
"""Build enriched triage CSV: workflow name, status, lifetime + active enrollments,
node count (from local dump if present), folder path, updated_at, id."""

import csv, json, os, sys, subprocess, urllib.parse

DIR = os.path.dirname(os.path.abspath(__file__))


def sh(cmd):
    return subprocess.check_output(cmd, shell=True, text=True).strip()


def fetch(token, url):
    out = subprocess.check_output([
        "curl", "-sS",
        "-H", f"token-id: {token}",
        "-H", "channel: APP",
        "-H", "version: 2021-04-15",
        "-H", "source: WEB_USER",
        "-H", "origin: https://client-app-automation-workflows.leadconnectorhq.com",
        "-H", "accept: application/json, text/plain, */*",
        url,
    ], text=True)
    return json.loads(out)


def main(loc, token):
    api = "https://backend.leadconnectorhq.com"

    tree = fetch(token, f"{api}/workflow/{loc}/list?limit=500&offset=0&sortBy=name&sortOrder=asc&includeCustomObjects=true&includeObjectiveBuilder=true")
    rows = tree["rows"]
    folders = {r["_id"]: r for r in rows if r["type"] == "directory"}
    workflows = [r for r in rows if r["type"] == "workflow"]

    if not workflows:
        print("no workflows found", file=sys.stderr)
        return

    qs = "&".join(f"workflowIds[]={urllib.parse.quote(w['_id'])}" for w in workflows)
    stats_list = fetch(token, f"{api}/workflows/status/search/enroll-stats-cache?{qs}&locationId={loc}")
    stats = {s["workflowId"]: s for s in stats_list}

    def folder_path(folder_id):
        if not folder_id:
            return ""
        parts, cur, seen = [], folder_id, set()
        while cur and cur not in seen:
            seen.add(cur)
            f = folders.get(cur)
            if not f: break
            parts.append(f["name"])
            cur = f.get("parentId")
        return " > ".join(reversed(parts))

    out_path = os.path.join(DIR, "reports", f"{loc}-triage.csv")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["name", "status", "total_enrolled", "currently_enrolled",
                    "node_count", "folder", "updated_at", "workflow_id"])
        for wf in sorted(workflows, key=lambda x: x["name"].lower()):
            wid = wf["_id"]
            s = stats.get(wid, {})
            total = s.get("total", 0)
            active = total - s.get("finished", 0)
            wf_json = os.path.join(DIR, "workflows", loc, f"{wid}.json")
            try:
                with open(wf_json) as wf_f:
                    node_count = len(json.load(wf_f).get("workflowData", {}).get("templates", []))
            except FileNotFoundError:
                node_count = ""
            w.writerow([wf["name"], wf["status"], total, active, node_count,
                        folder_path(wf.get("parentId")), wf.get("updatedAt", ""), wid])

    print(f"wrote {out_path}", file=sys.stderr)
    print(f"  {len(workflows)} workflows  {len(folders)} folders", file=sys.stderr)
    ever = sum(1 for w in workflows if stats.get(w["_id"], {}).get("total", 0) > 0)
    print(f"  {ever} ever used  {len(workflows)-ever} never used", file=sys.stderr)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: triage.py <location_id> <token>", file=sys.stderr)
        sys.exit(1)
    main(sys.argv[1], sys.argv[2])
