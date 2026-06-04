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

# ── Ensure database exists ──────────────────────────
#   (launcher starts MySQL; this just creates the DB if missing)
try:
    import pymysql
    c = pymysql.connect(host='127.0.0.1', user='root', password='', autocommit=True)
    with c.cursor() as cur:
        cur.execute("CREATE DATABASE IF NOT EXISTS data_ledger CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    c.close()
except Exception as ex:
    print(f"[startup] DB check: {ex}")

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
    # Windows：用 netstat 查找占用端口的 PID
    result = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, timeout=5
    )
    for line in result.stdout.splitlines():
        if f":{PORT}" in line and ("LISTENING" in line or "ESTABLISHED" in line):
            parts = line.strip().split()
            if parts:
                pid = parts[-1]
                subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, timeout=5)
                print(f"  OK 释放端口 {PORT}（PID {pid}）")
                break
except Exception:
    print(f"  ! 无法自动释放端口 {PORT}，请手动关闭占用 5000 端口的程序")

# ── Run ──────────────────────────────────────────────
if __name__ == '__main__':
    print("=" * 50)
    print("数据台账系统 — 服务器")
    print(f"  Python: {sys.version.split()[0]}")
    print(f"  Base:   {BASE}")
    print(f"  Data:   {DATA_DIR}")
    print(f"  端口:   5000")
    print("=" * 50)
    data_ledger_app.app.run(host='0.0.0.0', port=5000, debug=False)
