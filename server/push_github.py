#!/usr/bin/env python3
"""Push road-ledger changes to GitHub via API (no git CLI needed)"""
import os, sys, json, base64, urllib.request, ssl
from datetime import datetime

REPO_DIR = r"E:\data\road-ledger-main\road-ledger-main"
OWNER = "1013059024"
REPO = "road-ledger"
BRANCH = "main"
TOKEN = "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"
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

def get_or_create_blob(content):
    blob = api('POST', '/git/blobs', {
        'content': base64.b64encode(content).decode('ascii'),
        'encoding': 'base64'
    })
    return blob['sha']

def main():
    print(f"Pushing {REPO_DIR} → {OWNER}/{REPO} ({BRANCH})")
    
    # 1. Get current HEAD
    ref = api('GET', f'/git/ref/heads/{BRANCH}')
    current_sha = ref['object']['sha']
    print(f"  HEAD: {current_sha[:10]}")

    # 2. Walk files
    IGNORE = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
              'dist', 'build', '.idea', '.vscode', '*.pyc'}
    tree_items = []
    for root, dirs, files in os.walk(REPO_DIR):
        dirs[:] = [d for d in dirs if d not in IGNORE and not d.startswith('.')]
        for fn in sorted(files):
            if fn.endswith('.pyc'): continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, REPO_DIR).replace('\\', '/')
            try:
                with open(fp, 'rb') as fh: content = fh.read()
            except: continue
            blob_sha = get_or_create_blob(content)
            tree_items.append({
                'path': rel, 'mode': '100644',
                'type': 'blob', 'sha': blob_sha
            })
    
    print(f"  Files: {len(tree_items)}")

    # 3. Create tree (with existing tree as base to preserve unmodified files)
    # First get the current tree to merge
    current_commit = api('GET', f'/git/commits/{current_sha}')
    base_tree = api('GET', f'/git/trees/{current_commit["tree"]["sha"]}')

    # Build a dict of existing files from base tree
    existing = {}
    def walk_tree(tree_sha, prefix=''):
        t = api('GET', f'/git/trees/{tree_sha}')
        for item in t['tree']:
            path = f"{prefix}/{item['path']}" if prefix else item['path']
            if item['type'] == 'tree':
                walk_tree(item['sha'], path)
            else:
                existing[path] = item['sha']
    walk_tree(current_commit['tree']['sha'])

    # Update with new file hashes
    for item in tree_items:
        existing[item['path']] = item['sha']
    
    new_tree_items = [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': s}
                      for p, s in existing.items()]
    
    new_tree = api('POST', '/git/trees', {'tree': new_tree_items})
    print(f"  Tree: {new_tree['sha'][:10]}... ({len(new_tree_items)} entries)")

    # 4. Create commit
    msg = f"Auto-sync {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    new_commit = api('POST', '/git/commits', {
        'message': msg,
        'tree': new_tree['sha'],
        'parents': [current_sha]
    })
    print(f"  Commit: {new_commit['sha'][:10]}")

    # 5. Update branch
    api('PATCH', f'/git/refs/heads/{BRANCH}', {
        'sha': new_commit['sha'], 'force': True
    })
    print(f"  ✅ Pushed to {OWNER}/{REPO}")

if __name__ == '__main__':
    main()
