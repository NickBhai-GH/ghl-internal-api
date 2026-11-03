#!/usr/bin/env python3
"""Index every GHL API call in the toolkit's HAR captures.

Usage:  python3 -I har_index.py            (run from anywhere)
        python3 -I har_index.py --selftest

Writes (all redacted: tokens, cookies, emails, phones, contact names):
  HAR_ENDPOINTS.md      every distinct endpoint, grouped by domain, with
                        sources, statuses, query keys, body + response shapes
  HAR_FILES.md          one block per HAR: account, locations, what it hit
  ENDPOINT_INDEX.md     method + templated path only (safe to share)
  har/index.json        same data as JSON (local only, har/ is not synced)

Re-run after dropping a new HAR in har/. Curated notes live in HAR_NOTES.md,
which this script never touches.
"""
import json, re, sys, glob, os, collections
from urllib.parse import urlsplit, parse_qsl

ROOT = os.path.dirname(os.path.abspath(__file__))
API_HOST = re.compile(r'(leadconnectorhq\.com|msgsndr\.com|gohighlevel\.com|apisystem\.tech'
                      r'|firestore\.googleapis|identitytoolkit\.googleapis|securetoken\.googleapis'
                      r'|firebasestorage\.googleapis)')
SKIP_HOST = re.compile(r'pathfinder|stcdn\.|app-manifest')   # telemetry, static assets
SECRET_KEY = re.compile(r'token|password|secret|refresh|authori|cookie|apikey|api_key|signature|otp|code_verifier', re.I)
PII_KEY = re.compile(r'^(email|emails?Address|phone|phoneNumber|firstName|lastName|fullName|contactName|'
                     r'firstNameRaw|lastNameRaw|address1|dateOfBirth|to|from|emailTo|cc|bcc)$', re.I)
EMAIL = re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')
PHONE = re.compile(r'\+?\d[\d\s()-]{9,}\d')
JWT = re.compile(r'eyJ[\w-]+\.[\w-]+\.[\w-]+')
UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.I)
OID = re.compile(r'^[0-9a-f]{24}$')
GID = re.compile(r'^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{16,36}$')   # GHL/Firebase ids
STATIC = re.compile(r'\.(js|css|svg|png|jpe?g|gif|webp|woff2?|ttf|ico|map)$|/i18n/|/cdn-cgi/', re.I)
WHITELABEL = re.compile(r'https://(app\.[\w.-]+)')
NOISY_HEADERS = {'accept', 'accept-encoding', 'accept-language', 'connection', 'content-length', 'host',
                 'origin', 'referer', 'user-agent', 'sec-fetch-dest', 'sec-fetch-mode', 'sec-fetch-site',
                 'sec-ch-ua', 'sec-ch-ua-mobile', 'sec-ch-ua-platform', 'priority', 'cache-control', 'pragma',
                 'token-id', 'authorization', 'cookie', 'baggage', 'sentry-trace', 'dnt', 'if-none-match',
                 ':authority', ':method', ':path', ':scheme', 'content-type', 'x-client-data', 'traceparent'}


def scrub_str(s):
    s = JWT.sub('<jwt>', s)
    s = EMAIL.sub('<email>', s)
    return PHONE.sub('<phone>', s)


def redact(v, key=''):
    if key and SECRET_KEY.search(key) and not isinstance(v, (dict, list, bool)) and v not in (None, ''):
        return '<redacted>'
    if key and PII_KEY.match(key) and isinstance(v, str) and v:
        return '<pii>'
    if isinstance(v, dict):
        contact = any(k in v for k in ('contactId', 'contact_id', 'firstName', 'dnd', 'dateOfBirth'))
        return {k: '<pii>' if contact and k == 'name' and isinstance(x, str) else redact(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [redact(x, key) for x in v]
    if isinstance(v, str):
        return scrub_str(v)
    return v


def shape(v, depth=0):
    """Type skeleton: dicts keep keys, lists keep their first item."""
    if depth > 5:
        return '…'
    if isinstance(v, dict):
        items = list(v.items())
        out = {k: shape(x, depth + 1) for k, x in items[:40]}
        if len(items) > 40:
            out['…'] = f'+{len(items) - 40} keys'
        return out
    if isinstance(v, list):
        return [shape(v[0], depth + 1)] if v else []
    return type(v).__name__ if v is not None else 'null'


def clip(v, n=1500):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + f' …(+{len(s) - n} chars)'


def template(path, locs):
    out = []
    for seg in path.split('/'):
        if not seg:
            continue
        if seg in locs:
            out.append('{locationId}')
        elif UUID.match(seg):
            out.append('{uuid}')
        elif OID.match(seg):
            out.append('{id}')
        elif GID.match(seg):
            out.append('{id}')
        elif seg.startswith('acct_'):
            out.append('{stripeAccount}')
        elif seg.startswith('location%2F'):    # Firebase Storage object path, e.g. email HTML
            out.append('{storageObject}')
        elif seg.isdigit():
            out.append('{n}')
        elif EMAIL.search(seg):
            out.append('{email}')
        else:
            out.append(seg)
    return '/' + '/'.join(out)


def domain_of(host, tpath):
    if 'googleapis' in host:
        return 'firebase-' + host.split('.')[0]
    segs = [s for s in tpath.split('/') if s and not s.startswith('{') and s not in ('v1', 'v2', 'v3', 'api')]
    if not segs:
        return 'misc'
    if segs[0] in ('locations', 'location') and len(segs) > 1:
        return 'locations/' + segs[1]
    return segs[0]


def parse_body(text, mime=''):
    if not text:
        return None
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        if 'x-www-form-urlencoded' in mime:
            return {k: v for k, v in parse_qsl(text)}
        return scrub_str(text[:300])


def known_locations(entries):
    locs = set()
    for e in entries:
        u = urlsplit(e['request']['url'])
        for k, v in parse_qsl(u.query):
            if k in ('locationId', 'location_id', 'altId') and GID.match(v):
                locs.add(v)
        m = re.search(r'/locations?/([A-Za-z0-9]{20})(?:/|$)', u.path)
        if m:
            locs.add(m.group(1))
    return locs


def index(files):
    eps = {}
    per_file = []
    for f in files:
        try:
            entries = json.load(open(f, encoding='utf-8'))['log']['entries']
        except Exception as ex:   # a truncated or non-HAR file should not kill the run
            per_file.append({'file': f, 'error': str(ex)})
            continue
        locs = known_locations(entries)
        wl = collections.Counter()
        hits, writes, times = collections.Counter(), [], []
        for e in entries:
            r, resp = e['request'], e.get('response', {})
            for h in r.get('headers', []):
                if h['name'].lower() in ('origin', 'referer'):
                    m = WHITELABEL.match(h['value'])
                    if m:
                        wl[m.group(1)] += 1
            u = urlsplit(r['url'])
            if (r['method'] == 'OPTIONS' or not API_HOST.search(u.netloc) or SKIP_HOST.search(u.netloc)
                    or STATIC.search(u.path)):
                continue
            times.append(e.get('startedDateTime', '')[:10])
            tp = template(u.path, locs)
            key = (r['method'], u.netloc, tp)
            ep = eps.setdefault(key, {'method': r['method'], 'host': u.netloc, 'path': tp,
                                      'domain': domain_of(u.netloc, tp), 'count': 0, 'files': set(),
                                      'status': collections.Counter(), 'query': {}, 'headers': {},
                                      'req_shape': None, 'req_sample': None, 'res_shape': None,
                                      'res_sample': None, 'err_sample': None})
            ep['count'] += 1
            ep['files'].add(os.path.relpath(f, ROOT))
            st = resp.get('status', 0)
            ep['status'][st] += 1
            for k, v in parse_qsl(u.query, keep_blank_values=True):
                if k not in ep['query']:
                    ep['query'][k] = '<id>' if v in locs or GID.match(v) or OID.match(v) else scrub_str(v)[:60]
            for h in r.get('headers', []):
                n = h['name'].lower()
                if n not in NOISY_HEADERS and not n.startswith('sec-') and not SECRET_KEY.search(n):
                    ep['headers'].setdefault(n, scrub_str(h['value'])[:80])
            pd = r.get('postData') or {}
            body = parse_body(pd.get('text'), pd.get('mimeType', ''))
            if body is not None and ep['req_sample'] is None:
                ep['req_shape'], ep['req_sample'] = shape(body), redact(body)
            ct = resp.get('content', {})
            rb = parse_body(ct.get('text') if ct.get('encoding') != 'base64' else None, ct.get('mimeType', ''))
            if rb is not None:
                if 200 <= st < 300 and ep['res_sample'] is None:
                    ep['res_shape'], ep['res_sample'] = shape(rb), redact(rb)
                elif st >= 400 and ep['err_sample'] is None:
                    ep['err_sample'] = redact(rb)
            hits[ep['domain']] += 1
            if r['method'] in ('POST', 'PUT', 'PATCH', 'DELETE') and 'googleapis' not in u.netloc:
                writes.append(f"{r['method']} {tp} → {st}")
        per_file.append({'file': os.path.relpath(f, ROOT), 'mb': round(os.path.getsize(f) / 1e6, 1),
                         'dates': sorted(set(t for t in times if t)), 'whitelabel': [w for w, _ in wl.most_common(3)],
                         'locations': sorted(locs), 'domains': dict(hits.most_common()),
                         'writes': list(dict.fromkeys(writes))})
    return eps, per_file


# Docs that count as "already documented". Extra globs: GHL_DOC_SOURCES="glob1:glob2".
DOC_SOURCES = [os.path.join(ROOT, '*.md'), os.path.join(ROOT, 'ghl.sh'), '~/.claude/skills/ghl-*/*.md'] + \
    [g for g in os.environ.get('GHL_DOC_SOURCES', '').split(':') if g]
GENERATED = ('HAR_ENDPOINTS.md', 'HAR_FILES.md', 'ENDPOINT_INDEX.md')


def doc_corpus():
    text = []
    for pat in DOC_SOURCES:
        for f in glob.glob(os.path.expanduser(pat)):
            if not f.endswith(GENERATED):
                text.append(open(f, encoding='utf-8', errors='replace').read())
    return '\n'.join(text)


def documented(tpath, corpus):
    """True if the docs mention this path, with any id style ({loc}, <loc>, a real id)."""
    segs = tpath.strip('/').split('/')
    while segs and segs[0].startswith('{'):
        segs.pop(0)
    if not segs:
        return False
    pat = '/'.join(r'[^/\s`\'"|)]+' if x.startswith('{') else re.escape(x) for x in segs)
    return re.search(r'(?<![\w-])' + pat + r'(?![\w-])', corpus) is not None


def write_md(eps, per_file):
    corpus = doc_corpus()
    for ep in eps.values():
        ep['documented'] = documented(ep['path'], corpus)
    by_dom = collections.defaultdict(list)
    for ep in eps.values():
        by_dom[ep['domain']].append(ep)
    L = ['# GHL internal API: every endpoint seen in the HAR captures', '',
         '_Generated by `har_index.py`. Do not hand-edit; curated notes go in `HAR_NOTES.md`._', '',
         f'{len(eps)} distinct endpoints across {len(per_file)} HAR files. Path ids are templated: '
         '`{locationId}` = a location seen in that capture, `{id}` = any other GHL/Mongo id, '
         '`{uuid}` = workflow node/step ids. Samples are redacted.', '',
         'Doc column: ✓ = already written up in a skill, memory, roadmap or ghl.sh; '
         '**new** = only known from the raw HAR so far.', '',
         'Status column: codes seen, with counts. A 2xx means the shape below is proven; '
         '4xx-only rows are failed attempts, useful for what NOT to send.', '', '## Domains', '']
    doms = sorted(by_dom, key=lambda d: (-sum(e['count'] for e in by_dom[d]), d))
    L += [f"- [{d}](#{re.sub(r'[^a-z0-9-]', '', d.lower().replace('/', '').replace(' ', '-'))}) "
          f"({len(by_dom[d])} endpoints, {sum(not e['documented'] for e in by_dom[d])} new)" for d in doms]
    for d in doms:
        L += ['', f'## {d}', '', '| Method | Host | Path | Seen | Status | Doc |', '|---|---|---|---|---|---|']
        rows = sorted(by_dom[d], key=lambda e: (e['path'], e['method']))
        for ep in rows:
            st = ', '.join(f'{k}×{v}' for k, v in sorted(ep['status'].items()))
            L.append(f"| {ep['method']} | {ep['host'].split('.')[0]} | `{ep['path']}` | {ep['count']} | {st} | {'✓' if ep['documented'] else '**new**'} |")
        for ep in rows:
            L += ['', f"### `{ep['method']} {ep['host']}{ep['path']}`", '',
                  f"Sources: {', '.join(sorted(ep['files']))}"]
            if ep['query']:
                L.append('Query: ' + ', '.join(f'`{k}={v}`' for k, v in ep['query'].items()))
            if ep['headers']:
                L.append('Extra headers: ' + ', '.join(f'`{k}: {v}`' for k, v in ep['headers'].items()))
            if ep['req_sample'] is not None:
                L += ['', 'Request body:', '```json', clip(ep['req_sample']), '```']
            if ep['res_shape'] is not None:
                L += ['', 'Response shape:', '```json', clip(ep['res_shape'], 1200), '```']
            if ep['err_sample'] is not None:
                L += ['', 'Error seen:', '```json', clip(ep['err_sample'], 400), '```']
    open(os.path.join(ROOT, 'HAR_ENDPOINTS.md'), 'w').write('\n'.join(L) + '\n')

    F = ['# GHL HAR captures: what is in each file', '',
         '_Generated by `har_index.py`. What each capture was FOR is in `HAR_NOTES.md`._', '']
    for p in sorted(per_file, key=lambda p: (p.get('dates') or ['9'])[0]):
        if 'error' in p:
            F += [f"## {p['file']}", '', f"Could not parse: {p['error']}", '']
            continue
        F += [f"## {p['file']}", '',
              f"- Captured: {', '.join(p['dates']) or 'n/a'} · {p['mb']} MB · whitelabel: {', '.join(p['whitelabel']) or 'n/a'}",
              f"- Locations: {', '.join(p['locations']) or 'none'}",
              f"- Domains hit: {', '.join(f'{k} ({v})' for k, v in p['domains'].items()) or 'no GHL API calls'}"]
        if p['writes']:
            F.append('- Writes:')
            F += [f'  - `{w}`' for w in p['writes'][:60]]
            if len(p['writes']) > 60:
                F.append(f"  - …+{len(p['writes']) - 60} more")
        F.append('')
    open(os.path.join(ROOT, 'HAR_FILES.md'), 'w').write('\n'.join(F))

    os.makedirs(os.path.join(ROOT, 'har'), exist_ok=True)
    dump = [{**ep, 'files': sorted(ep['files']), 'status': dict(ep['status'])} for ep in eps.values()]
    # Paths-only list: no samples, no sources, safe to publish.
    P = ['# GHL internal API: endpoint index', '',
         '_Generated by `har_index.py` from HAR captures of the GHL web app. Method and templated path only. '
         'Status: 2xx = a success was seen; err = only errors were seen. Shapes change without notice._', '',
         f'{len(eps)} endpoints.', '']
    for d in doms:
        P += [f'## {d}', '', '| Method | Host | Path | Status |', '|---|---|---|---|']
        for ep in sorted(by_dom[d], key=lambda e: (e['path'], e['method'])):
            ok = '2xx' if any(200 <= int(k) < 300 for k in ep['status']) else 'err'
            P.append(f"| {ep['method']} | {ep['host'].split('.')[0]} | `{ep['path']}` | {ok} |")
        P.append('')
    open(os.path.join(ROOT, 'ENDPOINT_INDEX.md'), 'w').write('\n'.join(P))

    json.dump({'endpoints': dump, 'files': per_file}, open(os.path.join(ROOT, 'har', 'index.json'), 'w'),
              indent=1, default=str)


def selftest():
    locs = {'LocAbcdefghij1234567'}
    assert template('/workflow/LocAbcdefghij1234567/0123456789abcdef01234567', locs) == '/workflow/{locationId}/{id}'
    assert template('/workflows/sticky-notes-all', locs) == '/workflows/sticky-notes-all'
    assert template('/locations/LocAbcdefghij1234567/customFields', locs) == '/locations/{locationId}/customFields'
    assert template('/x/0f8fad5b-d9cb-469f-a165-70867728950e', locs) == '/x/{uuid}'
    assert domain_of('backend.leadconnectorhq.com', '/locations/{locationId}/customFields') == 'locations/customFields'
    r = redact({'refresh_token': 'abc', 'email': 'a@b.co', 'name': 'WF 1', 'note': 'call +44 7700 900123',
                'nested': [{'token-id': 'eyJa.b.c'}]})
    assert r == {'refresh_token': '<redacted>', 'email': '<pii>', 'name': 'WF 1', 'note': 'call <phone>',
                 'nested': [{'token-id': '<redacted>'}]}, r
    assert template('/sp/acct_1AbCdEfGhIjKlMnO', locs) == '/sp/{stripeAccount}'
    assert STATIC.search('/reporting.ff7e7dd0962b5375.js') and not STATIC.search('/reporting/dashboards')
    corpus = 'use `GET /workflows/sticky-notes-all?workflowId=` and /workflow/{loc}/{wf}/trigger'
    assert documented('/workflows/sticky-notes-all', corpus)
    assert documented('/workflow/{locationId}/{id}/trigger', corpus)
    assert not documented('/workflows/sticky-note', corpus)
    assert redact({'contactId': 'x', 'name': 'Jo Bloggs'}) == {'contactId': 'x', 'name': '<pii>'}
    assert shape({'a': [1, 2], 'b': None}) == {'a': ['int'], 'b': 'null'}
    print('selftest ok')


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        selftest()
        sys.exit()
    files = sorted(glob.glob(os.path.join(ROOT, '*.har')) + glob.glob(os.path.join(ROOT, 'har', '**', '*.har'), recursive=True))
    eps, per_file = index(files)
    write_md(eps, per_file)
    print(f'{len(files)} HARs → {len(eps)} endpoints. Wrote HAR_ENDPOINTS.md, HAR_FILES.md, ENDPOINT_INDEX.md, har/index.json')
