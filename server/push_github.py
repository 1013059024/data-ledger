#!/usr/bin/env python3
"""Push data-ledger to GitHub as a new Release (v3) preserving history"""
import os, sys, json, base64, urllib.request, ssl
from datetime import datetime

REPO_DIR = r"E:\reasonix-data\projects\data-ledger-windows-linux\data-ledger-windows-linux"
OWNER = "1013059024"
REPO = "data-ledger"
BRANCH = "windows/linux"
TAG = "v3.1"
TOKEN = os.environ.get("GITHUB_TOKEN", "")
ctx = ssl._create_unverified_context()

ARCHIVE_EXTS = {'.zip', '.rar', '.7z', '.tar.gz', '.tgz', '.gz'}

def api(method, path, data=None, accept=None):
    url = f"https://api.github.com/repos/{OWNER}/{REPO}{path}"
    headers = {
        'Authorization': f'token {TOKEN}',
        'User-Agent': 'data-ledger-sync',
        'Content-Type': 'application/json',
    }
    headers['Accept'] = accept or 'application/vnd.github.v3+json'
    req = urllib.request.Request(url, headers=headers, method=method)
    if data: req.data = json.dumps(data).encode('utf-8')
    try:
        resp = urllib.request.urlopen(req, timeout=60, context=ctx)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f'    API ERROR {e.code}: {body[:500]}', flush=True)
        raise

def get_or_create_blob(content):
    blob = api('POST', '/git/blobs', {
        'content': base64.b64encode(content).decode('ascii'),
        'encoding': 'base64'
    })
    return blob['sha']

def is_archive(fn):
    for ext in ARCHIVE_EXTS:
        if fn.endswith(ext): return True
    return False

def main():
    print(f"📦 推送 {REPO_DIR} → {OWNER}/{REPO} ({BRANCH}) 作为 {TAG} Release\n")

    # ── 1. 获取当前 HEAD ──
    ref = api('GET', f'/git/ref/heads/{BRANCH}')
    current_sha = ref['object']['sha']
    print(f"  HEAD: {current_sha[:10]}")

    # ── 2. 遍历本地文件（排除压缩包/数据/缓存）──
    IGNORE_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv',
                   'dist', 'build', '.idea', '.vscode', 'mysql-data',
                   '_tmp', '_backup', 'data-ledger-portable', 'target', 'data',
                   'example'}
    tree_items = []
    for root, dirs, files in os.walk(REPO_DIR):
        rel_root = os.path.relpath(root, REPO_DIR)
        if rel_root == '.':
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith('.')]
        else:
            top_dir = rel_root.split(os.sep)[0]
            if top_dir in IGNORE_DIRS or top_dir.startswith('.'):
                dirs.clear(); continue
        for fn in sorted(files):
            if fn.endswith('.pyc') or '.bak' in fn or is_archive(fn) or 'server_备份_' in fn:
                continue
            fp = os.path.join(root, fn)
            rel = os.path.relpath(fp, REPO_DIR).replace('\\', '/')
            try:
                with open(fp, 'rb') as fh: content = fh.read()
            except: continue
            print(f'  [{len(tree_items)+1}] {rel} ({len(content)} bytes)', flush=True); blob_sha = get_or_create_blob(content)
            tree_items.append({
                'path': rel, 'mode': '100644',
                'type': 'blob', 'sha': blob_sha
            })
    print(f"  文件数: {len(tree_items)}")

    # ── 3. 合并远端树（保留远端有但本地未变的文件）──
    current_commit = api('GET', f'/git/commits/{current_sha}')

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

    # 本地文件覆盖 + 远端已删除的文件清理
    local_paths = {item['path'] for item in tree_items}
    for item in tree_items:
        existing[item['path']] = item['sha']
    deleted = [p for p in existing if p not in local_paths]
    for p in deleted:
        del existing[p]
    if deleted:
        for p in deleted: print(f"  🗑 删除: {p}")

    new_tree_items = [{'path': p, 'mode': '100644', 'type': 'blob', 'sha': s}
                      for p, s in existing.items()]
    new_tree = api('POST', '/git/trees', {'tree': new_tree_items})
    print(f"  树: {new_tree['sha'][:10]}... ({len(new_tree_items)} 项)")

    # ── 4. 创建提交 ──
    commit_msg = (f"v3.1 Windows 最新稳定版 "
                  f"({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    new_commit = api('POST', '/git/commits', {
        'message': commit_msg,
        'tree': new_tree['sha'],
        'parents': [current_sha]
    })
    print(f"  提交: {new_commit['sha'][:10]}")

    # ── 5. 更新 main 分支 ──
    api('PATCH', f'/git/refs/heads/{BRANCH}', {
        'sha': new_commit['sha'], 'force': True
    })
    print(f"  ✅ main 分支已更新")

    # ── 6. 创建 Tag ──
    tagger = {"name": "1013059024", "email": "1013059024@users.noreply.github.com",
              "date": datetime.utcnow().isoformat() + "Z"}
    tag_obj = api('POST', '/git/tags', {
        'tag': TAG,
        'message': f'Release {TAG}',
        'object': new_commit['sha'],
        'type': 'commit',
        'tagger': tagger
    })
    print(f"  Tag 对象: {tag_obj['sha'][:10]}")

    # 创建 tag 引用
    try:
        api('POST', '/git/refs', {
            'ref': f'refs/tags/{TAG}',
            'sha': new_commit['sha']
        })
        print(f"  ✅ Tag {TAG} 已创建")
    except urllib.error.HTTPError as e:
        if e.code == 422:
            print(f"  ⚠️ Tag {TAG} 已存在，强制更新")
            api('PATCH', f'/git/refs/tags/{TAG}', {
                'sha': new_commit['sha'], 'force': True
            })
        else:
            raise

    # ── 7. 创建 Release ──
    try:
        release = api('POST', '/releases', {
            'tag_name': TAG,
            'name': f'v3.1 - Windows 稳定版',
            'body': (
                '## ✨ 新功能\n\n'
                '- **去重预览**：去重前弹窗显示每条重复记录的完整字段信息\n'
                '- **单文件 EXE**：PyInstaller 打包为 农村公路台账.exe（87MB）\n\n'
                '## 🔄 更名\n\n'
                '- **农村公路台账 → 数据台账系统**\n'
                '- **road-ledger → data-ledger**\n'
                '- **GitHub 仓库同步更名**\n'
            ),
            'draft': False,
            'prerelease': False
        })
        print(f"  ✅ Release {TAG} 已创建: {release['html_url']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  ❌ Release 创建失败: {e.code} {body[:200]}")

if __name__ == '__main__':
    main()
