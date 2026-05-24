#!/usr/bin/env python3
"""Push road-ledger to GitHub"""
import os, sys, json, base64, urllib.request, ssl
from datetime import datetime

# --- CONFIG ---
TOKEN = "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"
OWNER = "1013059024"
REPO = "road-ledger"
BRANCH = "main"

REPO_DIR = os.path.dirname(os.path.abspath(__file__))
ctx = ssl._create_unverified_context()

def api(method, path, data=None):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}{path}"
    headers = {
        'Authorization': f'token {TOKEN}',
        'User-Agent': 'road-ledger-sync',
        'Content-Type': 'application/json',
        'Accept': 'application/vnd.github.v3+json'
    }
    req = urllib.request.Request(url, headers=headers, method=method)
    if data: req.data = json.dumps(data).encode('utf-8')
    resp = urllib.request.urlopen(req, timeout=30, context=ctx)
    return json.loads(resp.read())

def main():
    print(f"Pushing → {OWNER}/{REPO} ({BRANCH})")
    ref = api('GET', f'/git/ref/heads/{BRANCH}')
    current_sha = ref['object']['sha']
    print(f"  HEAD: {current_sha[:10]}")

    IGNORE = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
              'dist', 'build', '.idea', '.vscode', '__pycache__', 'mysql-data'}
    tree_items = []
    for root, dirs, files in os.walk(REPO_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith('.')]
        for fn in sorted(files):
            if fn.endswith(('.pyc', '.pyo')): continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, REPO_DIR).replace('\\', '/')
            try:
                with open(fp, 'rb') as fh: content = fh.read()
            except: continue
            blob_sha = api('POST', '/git/blobs', {
                'content': base64.b64encode(content).decode('ascii'),
                'encoding': 'base64'
            })['sha']
            tree_items.append({'path': rel, 'mode': '100644', 'type': 'blob', 'sha': blob_sha})

    print(f"  Files: {len(tree_items)}")

    # Merge with existing tree
    current_commit = api('GET', f'/git/commits/{current_sha}')
    existing = {}
    def walk_tree(tree_sha, prefix=''):
        t = api('GET', f'/git/trees/{tree_sha}')
        for item in t['tree']:
            path = f"{prefix}/{item['path']}" if prefix else item['path']
            if item['type'] == 'tree': walk_tree(item['sha'], path)
            else: existing[path] = item['sha']
    walk_tree(current_commit['tree']['sha'])

    for item in tree_items:
        existing[item['path']] = item['sha']

    new_tree = api('POST', '/git/trees', {
        'tree': [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': s}
                 for p, s in existing.items()]
    })
    print(f"  Tree: {new_tree['sha'][:10]}")

    new_commit = api('POST', '/git/commits', {
        'message': f"Aggregate sync mapping features - {datetime.now():%Y-%m-%d %H:%M}",
        'tree': new_tree['sha'],
        'parents': [current_sha]
    })
    api('PATCH', f'/git/refs/heads/{BRANCH}', {
        'sha': new_commit['sha'], 'force': True
    })
    print(f"  ✅ {new_commit['sha'][:10]}")
    print(f"  https://github.com/{OWNER}/{REPO}")

if __name__ == '__main__':
    main()
