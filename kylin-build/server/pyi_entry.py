"""
PyInstaller entry point for road-ledger Flask server

When compiled with --onefile, PyInstaller extracts bundled files to
sys._MEIPASS temporary directory. This script:
  1. Detects frozen (exe) vs dev (script) mode
  2. Sets DATA_LEDGER_BASE = _MEIPASS (templates/static live here)
  3. Sets DATA_LEDGER_DATA = current working directory (configs/backups here)
  4. Patches Flask paths and imports the real app
  5. Starts the server
"""
import os
import sys

# ── Detect environment ──────────────────────────────
if getattr(sys, 'frozen', False):
    # Running as compiled EXE — extracted to temp dir
    BASE = sys._MEIPASS
    DATA_DIR = os.getcwd()
else:
    # Running as plain Python script (debug)
    BASE = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR = BASE

# Make sure data dir is writable
os.makedirs(DATA_DIR, exist_ok=True)

# Signal the real app where to look for things
os.environ['DATA_LEDGER_BASE'] = BASE
os.environ['DATA_LEDGER_DATA'] = DATA_DIR

# ── Import the real Flask app ──────────────────────
#   (add BASE to path so app.py finds its sibling modules)
sys.path.insert(0, BASE)

# ── Ensure data directory exists ────────────────────
#   SQLite database will be created automatically on first connection
os.makedirs(os.path.join(DATA_DIR, "data"), exist_ok=True)

import app as data_ledger_app

# Override Flask's template/static folders to point at the extracted bundle
data_ledger_app.app.root_path = BASE
data_ledger_app.app.template_folder = os.path.join(BASE, 'templates')
data_ledger_app.app.static_folder = os.path.join(BASE, 'static')
data_ledger_app.app.static_url_path = '/static'

# ── 端口释放 ──────────────────────────────────────
PORT = 5000
import subprocess
try:
    # 麒麟 Linux：杀掉占用 5000 端口的旧进程
    subprocess.run(
        ["fuser", "-k", f"{PORT}/tcp"],
        capture_output=True, timeout=5
    )
    print(f"  OK 释放端口 {PORT}")
except Exception:
    try:
        # 备选：lsof 方式
        result = subprocess.run(
            ["lsof", "-ti", f":{PORT}"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            pids = result.stdout.strip().split()
            subprocess.run(["kill", "-9"] + pids, capture_output=True, timeout=5)
            print(f"  OK 释放端口 {PORT}（lsof）")
    except Exception:
        print(f"  ! 无法自动释放端口 {PORT}，如启动失败请手动杀掉占用进程")

# ── Run ──────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("数据台账系统 — 服务器")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Base:   {BASE}")
    print(f"  Data:   {DATA_DIR}")
    print(f"  端口:   {PORT}")
    print("=" * 50)
    data_ledger_app.app.run(host='0.0.0.0', port=PORT, debug=False)
